import json
import sys
from pathlib import Path
from typing import Any

import pytest

import cfn_typed as cfn

sys.path.insert(0, str(Path(__file__).parent.parent / "examples"))

from web_stack import build  # noqa: E402


def test_ssm_parameter_is_declared_and_returns_a_ref() -> None:
    params = cfn.Params()
    vpc = params.ssm("VpcId", "/platform/network/vpc-id", description="Shared VPC")
    assert vpc == {"Ref": "VpcId"}
    assert params.declarations() == {"VpcId": {
        "Type": "AWS::SSM::Parameter::Value<String>", "Default": "/platform/network/vpc-id", "Description": "Shared VPC",
    }}
    assert params.ssm_list("Subnets", "/x")["Ref"] == "Subnets"
    assert params.declarations()["Subnets"]["Type"] == "AWS::SSM::Parameter::Value<List<String>>"


def test_plain_parameters() -> None:
    params = cfn.Params()
    params.string("Stage", default="dev", allowed_values=["dev", "prod"])
    params.string("Secret", no_echo=True)
    params.number("Size", default=3)
    assert params.declarations() == {
        "Stage": {"Type": "String", "Default": "dev", "AllowedValues": ["dev", "prod"]},
        "Secret": {"Type": "String", "NoEcho": True},
        "Size": {"Type": "Number", "Default": 3},
    }


def test_parameter_constraints() -> None:
    params = cfn.Params()
    params.string(
        "Code", default="ab", min_length=2, max_length=8, allowed_pattern="[a-z]+", constraint_description="lower case",
    )
    params.number("Size", default=3, min_value=1, max_value=10, constraint_description="1 to 10")
    assert params.declarations() == {
        "Code": {
            "Type": "String", "Default": "ab", "AllowedPattern": "[a-z]+", "MinLength": 2, "MaxLength": 8,
            "ConstraintDescription": "lower case",
        },
        "Size": {"Type": "Number", "Default": 3, "MinValue": 1, "MaxValue": 10, "ConstraintDescription": "1 to 10"},
    }


def test_template_sections_beyond_resources() -> None:
    template: cfn.Template = {
        "Transform": "AWS::Serverless-2016-10-31",
        "Metadata": {"AWS::CloudFormation::Interface": {"ParameterGroups": []}},
        "Parameters": {"Size": {"Type": "Number", "MinValue": 1, "MaxValue": 2.5}},
        "Rules": {"R": {"Assertions": []}},
        "Resources": {},
    }
    assert list(json.loads(cfn.to_json(template))) == ["Transform", "Metadata", "Parameters", "Rules", "Resources"]


def test_redeclaring_the_same_parameter_is_fine_but_a_conflict_is_not() -> None:
    params = cfn.Params()
    assert params.ssm("VpcId", "/a") == params.ssm("VpcId", "/a")
    with pytest.raises(ValueError, match="already declared"):
        params.ssm("VpcId", "/b")


def test_bad_names_and_paths_are_rejected() -> None:
    params = cfn.Params()
    with pytest.raises(ValueError, match="letters and digits"):
        params.string("vpc-id")
    with pytest.raises(ValueError, match="needs a path"):
        params.ssm("Empty", "")


def test_declarations_are_a_copy() -> None:
    params = cfn.Params()
    params.string("A")
    params.declarations().clear()
    assert "A" in params.declarations()


def test_dynamic_references() -> None:
    assert cfn.dynamic_ssm("/app/key") == "{{resolve:ssm:/app/key}}"
    assert cfn.dynamic_ssm("/app/key", version=3) == "{{resolve:ssm:/app/key:3}}"
    assert cfn.dynamic_ssm("/app/pw", secure=True, version=1) == "{{resolve:ssm-secure:/app/pw:1}}"


def refs(node: Any) -> set[str]:
    if isinstance(node, dict):
        found = {node["Ref"]} if set(node) == {"Ref"} else set()
        return found.union(*(refs(v) for v in node.values()))
    if isinstance(node, list):
        return set().union(*(refs(v) for v in node))
    return set()


def test_example_stack_only_declares_what_it_uses_and_every_ref_resolves() -> None:
    template: Any = json.loads(cfn.to_json(build()))
    assert set(template["Parameters"]) == {"VpcId", "PrivateSubnets", "Stage"}
    assert refs(template["Resources"]) <= set(template["Resources"]) | set(template["Parameters"])
    lb = template["Resources"]["WebLoadBalancer"]["Properties"]
    assert lb["Subnets"] == {"Ref": "PrivateSubnets"}  # a list-typed parameter used directly


def test_yaml_for_the_example_uses_short_forms() -> None:
    text = cfn.to_yaml(build())
    assert "Type: AWS::SSM::Parameter::Value<List<String>>" in text
    assert "Subnets: !Ref PrivateSubnets" in text
