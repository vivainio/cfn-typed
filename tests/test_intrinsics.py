from typing import Any

import pytest

import cfn_typed as cfn
from cfn_typed import (
    and_, base64, cidr, condition_ref, equals, find_in_map, get_att, get_azs, if_, import_value, join, not_, or_, ref, select, split, sub,
)


def test_each_builder_makes_the_dict_cloudformation_expects() -> None:
    assert ref("Q") == {"Ref": "Q"}
    assert get_att("Q", "Arn") == {"Fn::GetAtt": ["Q", "Arn"]}
    assert get_att("Q", ref("Which")) == {"Fn::GetAtt": ["Q", {"Ref": "Which"}]}
    assert sub("${A}") == {"Fn::Sub": "${A}"}
    assert sub("${A}-${B}", {"A": "x", "B": ref("P")}) == {"Fn::Sub": ["${A}-${B}", {"A": "x", "B": {"Ref": "P"}}]}
    assert join("/", ["", "a", ref("P")]) == {"Fn::Join": ["/", ["", "a", {"Ref": "P"}]]}
    assert select(0, get_azs()) == {"Fn::Select": [0, {"Fn::GetAZs": ""}]}
    assert split(",", "a,b") == {"Fn::Split": [",", "a,b"]}
    assert find_in_map("M", ref("Stage"), "Key") == {"Fn::FindInMap": ["M", {"Ref": "Stage"}, "Key"]}
    assert if_("C", 1, ref("AWS::NoValue")) == {"Fn::If": ["C", 1, {"Ref": "AWS::NoValue"}]}
    assert get_azs(ref("AWS::Region")) == {"Fn::GetAZs": {"Ref": "AWS::Region"}}
    assert base64("x") == {"Fn::Base64": "x"}
    assert cidr("10.0.0.0/16", 4, 8) == {"Fn::Cidr": ["10.0.0.0/16", 4, 8]}
    assert import_value(sub("${S}-Vpc")) == {"Fn::ImportValue": {"Fn::Sub": "${S}-Vpc"}}


def test_builders_do_not_share_or_alias_their_inputs() -> None:
    variables = {"A": "x"}
    result = sub("${A}", variables)
    variables["A"] = "changed"
    assert result == {"Fn::Sub": ["${A}", {"A": "x"}]}


def test_condition_functions() -> None:
    assert equals(ref("Stage"), "prod") == {"Fn::Equals": [{"Ref": "Stage"}, "prod"]}
    assert condition_ref("IsProd") == {"Condition": "IsProd"}
    both = and_(condition_ref("A"), equals("x", "y"))
    assert both == {"Fn::And": [{"Condition": "A"}, {"Fn::Equals": ["x", "y"]}]}
    assert or_(condition_ref("A"), condition_ref("B")) == {"Fn::Or": [{"Condition": "A"}, {"Condition": "B"}]}
    assert not_(both) == {"Fn::Not": [both]}


def test_and_or_take_between_two_and_ten_conditions() -> None:
    one, many = [condition_ref("A")], [condition_ref(f"C{i}") for i in range(11)]
    for builder in (and_, or_):
        with pytest.raises(ValueError, match="between 2 and 10"):
            builder(*one)
        with pytest.raises(ValueError, match="between 2 and 10"):
            builder(*many)
        builder(*many[:10])  # ten is allowed, so this does not raise


def test_a_template_takes_typed_conditions_and_renders_them() -> None:
    template: cfn.Template = {
        "Conditions": {"IsProd": equals(ref("Stage"), "prod"), "NotProd": not_(condition_ref("IsProd"))},
        "Resources": {},
    }
    text = cfn.to_yaml(template)
    assert "IsProd: !Equals" in text and "NotProd: !Not" in text and "- Condition: IsProd" in text


def test_pseudo_parameters_are_plain_refs() -> None:
    loose: Any = ref("AWS::Region")
    assert loose == {"Ref": "AWS::Region"}
