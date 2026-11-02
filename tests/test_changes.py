import json
import zipfile
from pathlib import Path
from typing import Any

import pytest

from cfn_typed import changes
from cfn_typed.changes import (
    Change,
    find_change_problems,
    find_deployed_differences,
    find_retention_problems,
    format_changes,
    get_deployed,
    parse_changes,
    plan,
    template_differences,
)
from cfn_typed.cli import StackSpec, main

DESCRIBED: dict[str, Any] = {"Status": "CREATE_COMPLETE", "Changes": [
    {"ResourceChange": {"Action": "Modify", "LogicalResourceId": "Fn", "ResourceType": "AWS::Lambda::Function", "Replacement": "False",
                        "Details": [{"Target": {"Attribute": "Properties", "Name": "MemorySize", "RequiresRecreation": "Never"}}]}},
    {"ResourceChange": {"Action": "Modify", "LogicalResourceId": "Dist", "ResourceType": "AWS::CloudFront::Distribution", "Replacement": "True",
                        "Details": [{"Target": {"Attribute": "Properties", "Name": "Origins", "RequiresRecreation": "Always"}}]}},
    {"ResourceChange": {"Action": "Modify", "LogicalResourceId": "Key", "ResourceType": "AWS::KMS::Key", "Replacement": "Conditional"}},
    {"ResourceChange": {"Action": "Remove", "LogicalResourceId": "Bucket", "ResourceType": "AWS::S3::Bucket"}},
    {"ResourceChange": {"Action": "Modify", "LogicalResourceId": "Role", "ResourceType": "AWS::IAM::Role", "Replacement": "True"}},
    {"ResourceChange": {"Action": "Add", "LogicalResourceId": "New", "ResourceType": "AWS::SQS::Queue"}},
]}


def test_the_change_set_is_parsed_and_only_stateful_losses_stop_the_deploy() -> None:
    found = parse_changes(DESCRIBED)
    assert [c.logical_id for c in found] == ["Fn", "Dist", "Key", "Bucket", "Role", "New"]
    assert found[1].details == ("Properties.Origins (always)",)
    assert find_change_problems(found) == [
        "Dist (AWS::CloudFront::Distribution) would be replaced (Properties.Origins (always))",
        "Key (AWS::KMS::Key) may be replaced",
        "Bucket (AWS::S3::Bucket) would be removed",
    ]
    assert len(find_change_problems(found, strict=True)) == 4  # the role replacement too
    assert "Dist" in format_changes(found) and format_changes([]) == "no changes"


class Fake:
    """A stand-in for the aws command line that records what it was asked and answers like CloudFormation."""

    def __init__(self, described: dict[str, Any] | list[dict[str, Any]], template: Any = None) -> None:
        self.described, self.template, self.calls = ([described] if isinstance(described, dict) else list(described)), template, []

    def __call__(self, args):
        self.calls.append(list(args))
        match args[1]:
            case "describe-change-set":
                return self.described.pop(0) if len(self.described) > 1 else self.described[0]
            case "get-template":
                return {"TemplateBody": self.template}
        return None


def test_plan_creates_reads_and_deletes_the_change_set() -> None:
    fake = Fake([{"Status": "CREATE_PENDING"}, DESCRIBED])
    found = plan("ledger-dev", {"Resources": {}}, runner=fake, poll=0)
    assert len(found) == 6
    kinds = [c[1] for c in fake.calls]
    assert kinds == ["create-change-set", "describe-change-set", "describe-change-set", "delete-change-set"]
    assert "UPDATE" in fake.calls[0] and "CAPABILITY_NAMED_IAM" in fake.calls[0]


def test_plan_says_no_changes_and_cleans_up_when_a_change_set_fails_with_it() -> None:
    fake = Fake({"Status": "FAILED", "StatusReason": "The submitted information didn't contain changes. Submit different information to create a change set."})
    assert plan("s", {"Resources": {}}, runner=fake) == []
    assert fake.calls[-1][1] == "delete-change-set"
    assert [c[1] for c in Fake({"Status": "CREATE_COMPLETE"}).calls] == []
    failing = Fake({"Status": "FAILED", "StatusReason": "Template format error"})
    with pytest.raises(RuntimeError, match="Template format error"):
        plan("s", {"Resources": {}}, runner=failing)
    assert failing.calls[-1][1] == "delete-change-set"


def test_plan_keeps_the_change_set_on_request_and_refuses_a_template_that_is_too_big() -> None:
    fake = Fake({"Status": "CREATE_COMPLETE", "Changes": []})
    assert plan("s", {"Resources": {}}, runner=fake, keep=True) == []
    assert "delete-change-set" not in [c[1] for c in fake.calls]
    with pytest.raises(ValueError, match="51,200"):
        plan("s", {"Resources": {"X": "x" * 60000}}, runner=Fake({}))


def test_the_deployed_template_comes_as_json_or_yaml() -> None:
    assert get_deployed("s", runner=Fake({}, {"Resources": {"A": {"Type": "AWS::SQS::Queue"}}})) == {"Resources": {"A": {"Type": "AWS::SQS::Queue"}}}
    yaml_text = "Resources:\n  A:\n    Type: AWS::SQS::Queue\n    Properties:\n      QueueName: !Ref N\n"
    assert get_deployed("s", runner=Fake({}, yaml_text))["Resources"]["A"]["Properties"] == {"QueueName": {"Ref": "N"}}
    fake = Fake({}, {})
    get_deployed("s", stage="Processed", runner=fake)
    assert "Processed" in fake.calls[0]


def test_template_differences_name_the_path() -> None:
    a = {"Resources": {"Q": {"Type": "AWS::SQS::Queue", "Properties": {"VisibilityTimeout": 30, "Tags": [{"Key": "a"}]}}, "New": {}}}
    b = {"Resources": {"Q": {"Properties": {"VisibilityTimeout": 60, "Tags": [{"Key": "a"}, {"Key": "b"}]}, "Type": "AWS::SQS::Queue"}, "Old": {}}}
    assert find_deployed_differences(a, b) == [
        "Resources.Q.Properties.VisibilityTimeout: rendered 30, deployed 60",
        "Resources.Q.Properties.Tags: 1 items rendered, 2 deployed",
        "Resources.New: only in the rendered template",
        "Resources.Old: only in the deployed template",
    ]
    assert template_differences(a, dict(reversed(list(a.items())))) == []


def test_stateful_resources_need_a_retaining_policy() -> None:
    template = {"Resources": {
        "T": {"Type": "AWS::DynamoDB::Table", "Properties": {}},
        "B": {"Type": "AWS::S3::Bucket", "DeletionPolicy": "Retain", "UpdateReplacePolicy": "Retain"},
        "S": {"Type": "AWS::SQS::Queue", "DeletionPolicy": "Delete", "UpdateReplacePolicy": "Snapshot"},
        "F": {"Type": "AWS::Lambda::Function"},
    }}
    assert find_retention_problems(template) == [
        "Resources.T (AWS::DynamoDB::Table): DeletionPolicy is not set, not Retain or Snapshot",
        "Resources.T (AWS::DynamoDB::Table): UpdateReplacePolicy is not set, not Retain or Snapshot",
        "Resources.S (AWS::SQS::Queue): DeletionPolicy is Delete, not Retain or Snapshot",
    ]


# the command line

def build() -> dict[str, Any]:
    return {"Resources": {"Dist": {"Type": "AWS::CloudFront::Distribution", "Properties": {}}}}


@pytest.fixture
def fake_aws(monkeypatch: pytest.MonkeyPatch):
    def install(fake: Fake) -> Fake:
        monkeypatch.setattr(changes, "aws_runner", lambda **_: fake)
        return fake

    return install


def test_check_plan_stops_on_a_stateful_replacement(fake_aws, capsys) -> None:
    fake = fake_aws(Fake(DESCRIBED))
    assert main({"site": StackSpec(build, stack_name="shop-site-dev")}, argv=["check", "--plan"], prog="x") == 1
    out = capsys.readouterr().out
    assert "site: 3 problem(s)" in out and "[plan] Dist" in out and "[plan] Bucket" in out and "changes to shop-site-dev:" in out
    assert "shop-site-dev" in fake.calls[0]
    assert main({"site": build}, argv=["check", "--plan", "--stack-name", "other"], prog="x") == 1 and "other" in fake.calls[-1]


def test_check_plan_passes_when_there_is_nothing_to_lose(fake_aws, capsys) -> None:
    fake_aws(Fake({"Status": "CREATE_COMPLETE", "Changes": [DESCRIBED["Changes"][0], DESCRIBED["Changes"][5]]}))
    assert main({"site": build}, argv=["check", "--plan"], prog="x") == 0
    assert "site: ok" in capsys.readouterr().out
    fake_aws(Fake({"Status": "FAILED", "StatusReason": "No updates are to be performed."}))
    assert main({"site": build}, argv=["check", "--plan"], prog="x") == 0 and "no changes to site" in capsys.readouterr().out


def test_check_deployed_lists_the_differences(fake_aws, capsys) -> None:
    fake_aws(Fake({}, build()))
    assert main({"site": build}, argv=["check", "--deployed"], prog="x") == 0 and "site: ok" in capsys.readouterr().out
    fake_aws(Fake({}, {"Resources": {}}))
    assert main({"site": build}, argv=["check", "--deployed"], prog="x") == 1 and "[deployed] Resources.Dist: only in the rendered" in capsys.readouterr().out


def test_an_aws_failure_is_not_a_template_problem(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    def broken(_args):
        raise RuntimeError("aws cloudformation get-template failed: Stack does not exist")

    monkeypatch.setattr(changes, "aws_runner", lambda **_: broken)
    assert main({"site": build}, argv=["check", "--deployed"], prog="x") == 2
    assert "Stack does not exist" in capsys.readouterr().err


def test_without_a_live_flag_check_never_calls_aws(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(**_: Any) -> None:
        raise AssertionError("check called aws")

    monkeypatch.setattr(changes, "aws_runner", forbidden)
    assert main({"site": build}, argv=["check"], prog="x") == 0


def test_live_runs_all_three(fake_aws, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    from cfn_typed import packaging

    monkeypatch.setattr(packaging, "s3_object_exists", lambda b, k, **_: False)

    def fns() -> dict[str, Any]:
        return {"Resources": {"Dep": {"Type": "AWS::S3::Bucket", "Properties": {}}, "A": {"Type": "AWS::Lambda::Function", "Properties": {"Code": {"S3Bucket": {"Ref": "Dep"}, "S3Key": "a.zip"}}}}}

    fake = fake_aws(Fake({"Status": "CREATE_COMPLETE", "Changes": []}, fns()))
    assert main({"x": fns}, argv=["check", "--live", "--bucket-name", "Dep=real"], prog="x") == 1
    out = capsys.readouterr().out
    assert "[code] Resources.A.Properties.Code: s3://real/a.zip does not exist" in out and "[deployed]" not in out and "[plan]" not in out
    assert {"get-template", "create-change-set"} <= {c[1] for c in fake.calls}


def test_check_can_require_retention(capsys) -> None:
    assert main({"site": build}, argv=["check", "--no-unused"], prog="x") == 0
    assert main({"site": build}, argv=["check", "--retention"], prog="x") == 1
    assert "[find_retention_problems]" in capsys.readouterr().out


def test_zip_command(tmp_path: Path, capsys) -> None:
    zipped = tmp_path / "a.zip"
    with zipfile.ZipFile(zipped, "w") as archive:
        archive.writestr("app.py", "def handler(e, c):\n    return {'ok': e['n']}\n")
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"n": 3}))
    assert main(argv=["zip", str(zipped), "--handler", "app.handler", "--invoke", str(event)], prog="x") == 0
    assert '"ok": 3' in capsys.readouterr().out
    assert main(argv=["zip", str(zipped), "--require", "nope.py"], prog="x") == 1
    assert main(argv=["zip", str(zipped), "--wsgi"], prog="x") == 1
    assert "missing wsgi_handler.py" in capsys.readouterr().out
