import json
import re
from pathlib import Path

import pytest

from cfn_typed.cli import StackSpec, main, skill_dir


def good() -> dict:
    return {"Resources": {"Q": {"Type": "AWS::SQS::Queue", "Properties": {}}}}


def bad() -> dict:
    return {"Resources": {"Q": {"Type": "AWS::SQS::Queue", "Properties": {"RedrivePolicy": {"Ref": "Missing"}}}}}


def run(stacks, *argv) -> int:
    return main(stacks, argv=list(argv), prog="stacks")


def test_emit_prints_one_stack(capsys) -> None:
    assert run(good, "emit", "-f", "json") == 0
    assert '"AWS::SQS::Queue"' in capsys.readouterr().out


def test_emit_many_needs_a_choice(capsys) -> None:
    assert run({"a": good, "b": good}, "emit") == 2


def test_emit_writes_a_directory(tmp_path) -> None:
    assert run({"a": good, "b": good}, "emit", "-o", str(tmp_path)) == 0
    assert (tmp_path / "a.yaml").exists() and (tmp_path / "b.yaml").exists()


def test_check_exit_status(capsys) -> None:
    assert run({"good": good, "bad": bad}, "check") == 1
    out = capsys.readouterr().out
    assert "good: ok" in out and "bad: 1 problem(s)" in out and "[references]" in out


def test_diff_update_then_match(tmp_path, capsys) -> None:
    assert run({"a": good}, "diff", str(tmp_path)) == 1
    assert run({"a": good}, "diff", str(tmp_path), "--update") == 0
    assert run({"a": good}, "diff", str(tmp_path)) == 0
    (tmp_path / "a.yaml").write_text("old\n")
    assert run({"a": good}, "diff", str(tmp_path)) == 1
    assert "--- " in capsys.readouterr().out


def test_unknown_stack_is_a_usage_error() -> None:
    with pytest.raises(SystemExit) as e:
        main({"a": good}, argv=["check", "nope"])
    assert e.value.code == 2


def test_resources_lists_id_type_and_name(capsys) -> None:
    def named() -> dict:
        return {"Resources": {
            "Jobs": {"Type": "AWS::SQS::Queue", "Properties": {"QueueName": "jobs"}},
            "Lb": {"Type": "AWS::ElasticLoadBalancingV2::LoadBalancer", "Properties": {"Name": "front"}},
            "Fn": {"Type": "AWS::Lambda::Function", "Properties": {}},
        }}

    assert run({"s": named}, "ls") == 0
    out = capsys.readouterr().out
    assert "s: 3 resource(s)" in out and "front" in out and "Jobs  queue" in out and out.count("jobs") == 1
    assert run({"s": named}, "ls", "-l") == 0
    assert "Jobs  AWS::SQS::Queue" in capsys.readouterr().out
    assert run({"s": named}, "ls", "-t", "aws::sqs::*") == 0
    out = capsys.readouterr().out
    assert "1 resource(s)" in out and "Fn" not in out


def test_ls_type_aliases(capsys) -> None:
    def stack() -> dict:
        return {"Resources": {
            "Q": {"Type": "AWS::SQS::Queue", "Properties": {}},
            "F": {"Type": "AWS::Lambda::Function", "Properties": {}},
            "R": {"Type": "AWS::IAM::Role", "Properties": {}},
            "P": {"Type": "AWS::IAM::ManagedPolicy", "Properties": {}},
        }}

    for flag, expected in [("lambda", "F"), ("queue", "Q"), ("function", "F"), ("policy", "P"), ("AWS::IAM::*", "RP")]:
        assert run({"s": stack}, "ls", "-t", flag) == 0
        out = capsys.readouterr().out
        found = "".join(k for k in "QFRP" if f"  {k}  " in out)
        assert sorted(found) == sorted(expected), flag


def test_ls_strips_the_iam_prefix(capsys) -> None:
    def stack() -> dict:
        return {"Resources": {
            "P": {"Type": "AWS::IAM::ManagedPolicy", "Properties": {}},
            "V": {"Type": "AWS::EC2::VPC", "Properties": {}},
        }}

    assert run({"s": stack}, "ls") == 0
    out = capsys.readouterr().out
    assert "P  ManagedPolicy" in out and "V  AWS::EC2::VPC" in out


def test_standalone_reads_template_files(tmp_path, capsys) -> None:
    pytest.importorskip("yaml")
    from cfn_typed.render import to_yaml

    template = {
        "Parameters": {"Stage": {"Type": "String", "Default": "dev"}},
        "Resources": {
            "Q": {"Type": "AWS::SQS::Queue", "Properties": {"QueueName": {"Fn::Sub": "jobs-${Stage}"}}},
            "F": {"Type": "AWS::Lambda::Function", "Properties": {"Role": {"Fn::GetAtt": ["Q", "Arn"]}}},
        },
        "Outputs": {"Url": {"Value": {"Ref": "Q"}}},
    }
    yaml_file, json_file = tmp_path / "t.yaml", tmp_path / "u.json"
    yaml_file.write_text(to_yaml(template))
    json_file.write_text(json.dumps(template))

    assert main(argv=["check", str(yaml_file), str(json_file)]) == 0
    assert "t: ok" in capsys.readouterr().out
    assert main(argv=["ls", str(yaml_file), "-t", "lambda"]) == 0
    assert "F  lambda" in capsys.readouterr().out
    # the YAML round trip is lossless: converting the YAML file gives the same JSON as the JSON file
    assert main(argv=["emit", str(yaml_file), "-f", "json"]) == 0
    assert json.loads(capsys.readouterr().out) == template


def test_standalone_needs_files(tmp_path) -> None:
    with pytest.raises(SystemExit) as e:
        main(argv=["check"])
    assert e.value.code == 2
    with pytest.raises(SystemExit) as e:
        main(argv=["check", str(tmp_path / "nope.yaml")])
    assert e.value.code == 2


def test_skill_prints_the_agent_skill(capsys) -> None:
    assert main(argv=["skill"], prog="cfn-typed") == 0
    out = capsys.readouterr().out
    assert out.startswith("---\nname: cfn-typed\n") and "cfn-typed import" in out
    assert f"Skill directory: `{skill_dir()}`" in out


def test_skill_dir_holds_the_linked_resources(capsys) -> None:
    assert main(argv=["skill", "--dir"], prog="cfn-typed") == 0
    directory = Path(capsys.readouterr().out.strip())
    assert (directory / "SKILL.md").is_file()
    links = re.findall(r"\]\((resources/[^)#]+)", (directory / "SKILL.md").read_text())
    assert links and all((directory / link).is_file() for link in links)


def test_stackspec_emit_writes_each_stack_to_its_own_directory(tmp_path) -> None:
    stacks = {"a": StackSpec(good, out=tmp_path / "x"), "b": StackSpec(good, out=str(tmp_path / "y"))}
    assert run(stacks, "emit") == 0
    assert (tmp_path / "x" / "a.yaml").exists() and (tmp_path / "y" / "b.yaml").exists()
    assert not (tmp_path / "x" / "b.yaml").exists()


def test_stackspec_emit_dash_prints_and_dir_overrides(tmp_path, capsys) -> None:
    stacks = {"a": StackSpec(good, out=tmp_path / "x")}
    assert run(stacks, "emit", "a", "-o", "-") == 0
    assert "AWS::SQS::Queue" in capsys.readouterr().out and not (tmp_path / "x").exists()
    assert run(stacks, "emit", "-o", str(tmp_path / "over")) == 0
    assert (tmp_path / "over" / "a.yaml").exists() and not (tmp_path / "x").exists()


def test_stackspec_emit_mixed_needs_a_directory_for_the_rest(tmp_path, capsys) -> None:
    stacks = {"a": StackSpec(good, out=tmp_path), "b": good}
    assert run(stacks, "emit") == 2
    assert "b" in capsys.readouterr().err and not list(tmp_path.iterdir())


def test_stackspec_diff_uses_each_stacks_directory(tmp_path, capsys) -> None:
    stacks = {"a": StackSpec(good, out=tmp_path / "x"), "b": StackSpec(good, out=tmp_path / "y")}
    assert run(stacks, "diff") == 1
    assert run(stacks, "diff", "--update") == 0
    assert run(stacks, "diff") == 0 and run(stacks, "diff", "a") == 0
    (tmp_path / "y" / "b.yaml").write_text("old\n")
    assert run(stacks, "diff", "a") == 0 and run(stacks, "diff", "b") == 1


def test_stackspec_diff_explicit_directory_still_wins(tmp_path) -> None:
    stacks = {"a": StackSpec(good, out=tmp_path / "x")}
    assert run(stacks, "diff", str(tmp_path / "other"), "--update") == 0
    assert (tmp_path / "other" / "a.yaml").exists() and not (tmp_path / "x").exists()


def test_diff_without_any_directory_is_an_error(capsys) -> None:
    assert run({"a": good}, "diff", "a") == 2
    assert "no directory" in capsys.readouterr().err


def test_stackspec_ls_shows_the_directory(tmp_path, capsys) -> None:
    assert run({"a": StackSpec(good, out=tmp_path)}, "ls") == 0
    assert f"-> {tmp_path}" in capsys.readouterr().out


# --- settings: a dataclass whose fields are flags ---

import enum
from dataclasses import dataclass, field
from typing import Literal


class Tier(enum.Enum):
    small = 1
    large = 2


@dataclass
class Settings:
    stage: str = "dev"
    memory: int = 1024
    debug: bool = False
    tier: Tier = Tier.small
    region: Literal["eu-west-1", "us-east-1"] = "eu-west-1"
    tags: list[str] = field(default_factory=list)


def queue_named(s: Settings) -> dict:
    return {"Resources": {"Q": {"Type": "AWS::SQS::Queue", "Properties": {"QueueName": f"{s.stage}-{s.memory}-{s.debug}-{s.tier.name}-{s.region}-{','.join(s.tags)}"}}}}


def test_settings_flags_reach_the_builder(capsys) -> None:
    assert main(queue_named, settings=Settings, argv=["emit", "--stage", "prod", "--memory", "2048", "--debug", "--tier", "large", "--tags", "a", "--tags", "b"]) == 0
    assert "prod-2048-True-large-eu-west-1-a,b" in capsys.readouterr().out


def test_settings_defaults_apply(capsys) -> None:
    assert main(queue_named, settings=Settings, argv=["emit"]) == 0
    assert "dev-1024-False-small-eu-west-1-" in capsys.readouterr().out


def test_settings_bad_values_are_usage_errors(capsys) -> None:
    for argv in (["emit", "--memory", "lots"], ["emit", "--tier", "huge"], ["emit", "--region", "mars"]):
        with pytest.raises(SystemExit) as e:
            main(queue_named, settings=Settings, argv=argv)
        assert e.value.code == 2


def test_builder_without_an_argument_still_works(capsys) -> None:
    assert main({"a": good, "b": queue_named}, settings=Settings, argv=["check", "--stage", "x"]) == 0


@dataclass
class Needs:
    stage: str = field(metadata={"env": "TEST_STAGE", "help": "which stage"})


def needs(s: Needs) -> dict:
    return {"Resources": {"Q": {"Type": "AWS::SQS::Queue", "Properties": {"QueueName": s.stage}}}}


def test_a_field_without_a_default_is_required(capsys, monkeypatch) -> None:
    monkeypatch.delenv("TEST_STAGE", raising=False)
    with pytest.raises(SystemExit) as e:
        main(needs, settings=Needs, argv=["emit"])
    assert e.value.code == 2
    assert "--stage" in capsys.readouterr().err


def test_required_field_can_come_from_the_environment(capsys, monkeypatch) -> None:
    monkeypatch.setenv("TEST_STAGE", "from-env")
    assert main(needs, settings=Needs, argv=["emit"]) == 0
    assert "from-env" in capsys.readouterr().out
    assert main(needs, settings=Needs, argv=["emit", "--stage", "flag"]) == 0
    assert "flag" in capsys.readouterr().out


def test_stackspec_settings_override_and_only_selected_stacks_need_them(capsys, monkeypatch) -> None:
    monkeypatch.delenv("TEST_STAGE", raising=False)
    stacks = {"a": queue_named, "b": StackSpec(needs, settings=Needs)}
    assert main(stacks, settings=Settings, argv=["emit", "a"]) == 0        # b's required --stage is not asked for
    with pytest.raises(SystemExit):
        main(stacks, settings=Settings, argv=["emit", "b"])
    assert main(stacks, settings=Settings, argv=["emit", "b", "--stage", "s"]) == 0
    assert "QueueName: s" in capsys.readouterr().out


def test_validation_in_post_init_is_a_usage_error(capsys) -> None:
    @dataclass
    class Checked:
        stage: str = "dev"

        def __post_init__(self) -> None:
            if self.stage == "prod":
                raise ValueError("prod needs a ticket")

    with pytest.raises(SystemExit) as e:
        main(StackSpec(lambda s: good(), settings=Checked), argv=["emit", "--stage", "prod"])
    assert e.value.code == 2
    assert "prod needs a ticket" in capsys.readouterr().err


def test_conflicting_declarations_and_clashing_names_are_rejected() -> None:
    @dataclass
    class A:
        stage: str = "dev"

    @dataclass
    class B:
        stage: int = 1

    @dataclass
    class Clash:
        format: str = "x"

    with pytest.raises(TypeError, match="different type"):
        main({"a": StackSpec(lambda s: good(), settings=A), "b": StackSpec(lambda s: good(), settings=B)}, argv=["ls"])
    with pytest.raises(TypeError, match="already an option"):
        main(StackSpec(lambda s: good(), settings=Clash), argv=["emit"])
    with pytest.raises(TypeError, match="template files"):
        main(settings=A, argv=["ls", "x.json"])


def test_settings_with_diff(tmp_path, capsys) -> None:
    assert main({"q": queue_named}, settings=Settings, argv=["diff", str(tmp_path), "--update", "--stage", "p"]) == 0
    assert "p-1024" in (tmp_path / "q.yaml").read_text()
    assert main({"q": queue_named}, settings=Settings, argv=["diff", str(tmp_path), "--stage", "p"]) == 0
    assert main({"q": queue_named}, settings=Settings, argv=["diff", str(tmp_path)]) == 1
