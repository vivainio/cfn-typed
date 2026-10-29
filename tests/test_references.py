from typing import Any

import pytest

from cfn_typed import get_att, ref, sub
from cfn_typed.references import find_reference_problems
from cfn_typed.testing import assert_references_resolve


def template(**resources: Any) -> dict[str, Any]:
    return {"Parameters": {"Stage": {"Type": "String"}}, "Conditions": {"IsProd": {"Fn::Equals": [ref("Stage"), "prod"]}}, "Resources": resources}


def queue(**extra: Any) -> dict[str, Any]:
    return {"Type": "AWS::SQS::Queue", **extra}


def test_a_consistent_template_has_no_problems() -> None:
    t = template(
        Jobs=queue(Condition="IsProd"),
        Fn={"Type": "X", "DependsOn": "Jobs", "Condition": "IsProd", "Properties": {
            "A": ref("Jobs"), "B": get_att("Jobs", "Arn"), "C": ref("AWS::Region"), "D": ref("Stage"),
            "E": sub("${Jobs.Arn}-${Stage}-${AWS::AccountId}-${!Literal}-${Local}", {"Local": "x"}),
            "F": {"Fn::If": ["IsProd", 1, 2]}, "G": {"Fn::GetAtt": "Jobs.Arn"},
            "Policy": {"Statement": [{"Effect": "Allow", "Condition": {"StringEquals": {"k": "v"}}}]},
        }},
    )
    t["Outputs"] = {"Url": {"Value": ref("Jobs"), "Condition": "IsProd"}}
    assert find_reference_problems(t) == []
    assert_references_resolve(t)


def test_dangling_references_are_found_with_where_and_a_suggestion() -> None:
    t = template(
        Jobs=queue(),
        Fn={"Type": "X", "DependsOn": ["Jbos"], "Condition": "IsDev", "Properties": {
            "A": ref("Jbos"), "B": get_att("Stage", "Arn"), "C": sub("${Nope.Arn}"), "D": {"Fn::If": ["IsProd2", 1, 2]},
            "E": {"Fn::FindInMap": ["Sizes", "a", "b"]},
        }},
    )
    t["Conditions"]["Both"] = {"Fn::And": [{"Condition": "IsProd"}, {"Condition": "Missing"}]}
    t["Outputs"] = {"Url": {"Value": ref("Jbos")}}
    problems = find_reference_problems(t)
    assert len(problems) == 9
    text = "\n".join(problems)
    assert "Resources.Fn.Properties.A: Ref refers to 'Jbos', which is not a resource or parameter (did you mean 'Jobs'?)" in text
    assert "Resources.Fn.Properties.B: Fn::GetAtt refers to 'Stage', which is not a resource" in text
    assert "Properties.C: Fn::Sub refers to 'Nope'" in text and "Properties.D: Fn::If refers to 'IsProd2'" in text
    assert "Properties.E: Fn::FindInMap refers to 'Sizes'" in text
    assert "Resources.Fn.DependsOn: DependsOn refers to 'Jbos'" in text and "Resources.Fn.Condition: Condition refers to 'IsDev'" in text
    assert "Conditions.Both" in text and "Outputs.Url" in text
    with pytest.raises(AssertionError, match="unresolved references"):
        assert_references_resolve(t)


def test_a_dependency_cycle_is_reported_and_a_self_reference_is() -> None:
    t = template(A={"Type": "X", "Properties": {"P": ref("B")}}, B={"Type": "X", "DependsOn": "C"}, C={"Type": "X", "Properties": {"P": get_att("A", "Arn")}})
    assert find_reference_problems(t) == ["Resources: circular dependency A -> B -> C -> A"]
    assert find_reference_problems(template(S={"Type": "X", "Properties": {"P": ref("S")}})) == ["Resources: circular dependency S -> S"]


def test_a_shared_dependency_is_not_a_cycle() -> None:
    t = template(Base=queue(), A={"Type": "X", "Properties": {"P": ref("Base")}}, B={"Type": "X", "Properties": {"P": ref("A"), "Q": ref("Base")}})
    assert find_reference_problems(t) == []
