import json
import re
from pathlib import Path

import pytest

from cfn_typed.cli import main, skill_dir


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
