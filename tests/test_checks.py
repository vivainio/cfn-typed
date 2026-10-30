from typing import Any

import pytest

from cfn_typed import get_att, ref, sub
from cfn_typed import typegen as gen
from cfn_typed.attributes import find_attribute_problems
from cfn_typed.limits import find_limit_problems
from cfn_typed.references import find_reference_problems, find_unused_problems
from cfn_typed.testing import assert_attributes_exist, assert_nothing_unused, assert_within_limits

GADGET: dict[str, Any] = {
    "typeName": "AWS::Foo::Gadget",
    "properties": {"Name": {"type": "string"}, "Arn": {"type": "string"}, "Endpoint": {"type": "object", "properties": {"Address": {"type": "string"}}}},
    "readOnlyProperties": ["/properties/Arn", "/properties/Endpoint/Address", "/properties/Rules/*/Id"],
    "primaryIdentifier": ["/properties/Name"],
}


def attrs() -> dict[str, Any]:
    ns: dict[str, Any] = {}
    exec(compile(gen.render_module("AWS::Foo", [GADGET]), "<gadget>", "exec"), ns)
    return ns["ATTRIBUTES"]


def test_generator_lists_read_only_and_identifier_properties() -> None:
    assert attrs() == {"AWS::Foo::Gadget": ["Arn", "Endpoint.Address", "Name"]}  # a path through a list has no GetAtt name


def test_getatt_attributes_are_checked_in_every_form() -> None:
    t = {"Resources": {
        "G": {"Type": "AWS::Foo::Gadget"},
        "H": {"Type": "AWS::Foo::Gadget", "Properties": {"A": get_att("G", "Arn"), "B": {"Fn::GetAtt": "G.Endpoint.Address"}, "C": sub("${G.Arn}")}},
    }, "Outputs": {"O": {"Value": get_att("G", "Nope")}}}
    assert find_attribute_problems(t, attrs()) == [
        "Outputs.O.Value: Fn::GetAtt asks 'G' (AWS::Foo::Gadget) for 'Nope', which is not one of its attributes",
    ]
    t["Resources"]["H"]["Properties"].update(D={"Fn::GetAtt": ["G", "Arnn"]}, E=sub("${G.Endpoint.Port}"), F=get_att("G", ref("P")))
    found = find_attribute_problems(t, attrs())
    assert any("for 'Arnn'" in p and "did you mean 'Arn'" in p for p in found) and any("Fn::Sub" in p for p in found)
    assert len(found) == 3  # the intrinsic attribute, a custom type and a type that was not generated are all skipped
    with pytest.raises(AssertionError, match="do not exist"):
        assert_attributes_exist(t, attrs())


def test_unknown_types_and_nested_stack_outputs_are_left_alone() -> None:
    t = {"Resources": {"C": {"Type": "Custom::X"}, "S": {"Type": "AWS::Foo::Gadget"}, "U": {"Type": "X", "Properties": {"A": get_att("C", "Anything"), "B": get_att("S", "Outputs.Url")}}}}
    assert find_attribute_problems(t, attrs()) == []


def cond_template(**resources: Any) -> dict[str, Any]:
    return {"Parameters": {"Stage": {"Type": "String"}}, "Conditions": {"IsProd": {"Fn::Equals": [ref("Stage"), "prod"]}, "Both": {"Fn::And": [{"Condition": "IsProd"}, {"Fn::Equals": [ref("Stage"), "x"]}]}}, "Resources": resources}


def test_a_reference_to_a_conditional_resource_must_be_guarded() -> None:
    t = cond_template(
        Jobs={"Type": "X", "Condition": "IsProd"},
        Same={"Type": "X", "Condition": "IsProd", "Properties": {"A": ref("Jobs")}},
        Stronger={"Type": "X", "Condition": "Both", "Properties": {"A": ref("Jobs")}},
        Guarded={"Type": "X", "Properties": {"A": {"Fn::If": ["IsProd", ref("Jobs"), "none"]}, "Dep": None}, "DependsOn": "Jobs"},
        Bare={"Type": "X", "Properties": {"A": ref("Jobs"), "B": {"Fn::If": ["IsProd", 1, get_att("Jobs", "Arn")]}, "C": sub("${Jobs}")}},
    )
    t["Outputs"] = {"Ok": {"Value": ref("Jobs"), "Condition": "IsProd"}, "Bad": {"Value": ref("Jobs")}}
    problems = find_reference_problems(t)
    assert [p.split(": ")[0] for p in problems] == [
        "Resources.Bare.Properties.A", "Resources.Bare.Properties.B.Fn::If[2]", "Resources.Bare.Properties.C", "Outputs.Bad.Value",
    ]
    assert "only exists when condition 'IsProd' holds" in problems[0]


def test_unused_parameters_conditions_and_mappings_are_listed() -> None:
    t = cond_template(R={"Type": "X", "Properties": {"A": {"Fn::FindInMap": ["Used", "a", "b"]}, "B": sub("${Stage}")}})
    t["Parameters"].update(Extra={"Type": "String"}, InRules={"Type": "String"})
    t["Mappings"] = {"Used": {}, "Idle": {}}
    t["Rules"] = {"r": {"Assertions": [{"Assert": {"Fn::Equals": [ref("InRules"), "x"]}}]}}
    assert find_unused_problems(t) == ["Parameters.Extra: never used", "Conditions.Both: never used", "Mappings.Idle: never used"]  # IsProd is used by Both
    t["Resources"]["R"]["Condition"] = "Both"  # Both is used, and it uses IsProd
    assert find_unused_problems(t) == ["Parameters.Extra: never used", "Mappings.Idle: never used"]
    with pytest.raises(AssertionError, match="unused"):
        assert_nothing_unused(t)


def test_limits_and_names() -> None:
    ok = {"Description": "x", "Resources": {"A": {"Type": "X"}}}
    assert find_limit_problems(ok) == []
    assert_within_limits(ok)
    big = {"Resources": {f"R{i}": {"Type": "X"} for i in range(501)}, "Parameters": {"bad-name": {}}, "Description": "é" * 600}
    text = "\n".join(find_limit_problems(big))
    assert "Resources: 501 entries" in text and "Parameters.bad-name: a logical ID" in text and "Description: 1200 bytes" in text
    assert find_limit_problems({"Resources": {"A": {"Type": "X", "Properties": {"P": "x" * 60_000}}}}) == []
    assert "Template: " in find_limit_problems({"Resources": {"A": {"Type": "X", "Properties": {"P": "x" * 60_000}}}}, inline=True)[0]
    with pytest.raises(AssertionError, match="limits"):
        assert_within_limits(big)


def test_one_call_runs_every_check_and_groups_the_problems(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib

    from cfn_typed.checks import find_all_problems
    from cfn_typed.testing import assert_template_ok

    pkg = tmp_path / "cfn_types_checks"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "foo.py").write_text(gen.render_module("AWS::Foo", [GADGET]))
    monkeypatch.syspath_prepend(str(tmp_path))
    types = importlib.import_module("cfn_types_checks")

    gadget = {"Type": "AWS::Foo::Gadget"}
    good = {"Resources": {"A": gadget, "B": {"Type": "X", "Properties": {"P": get_att("A", "Arn")}}}}
    assert find_all_problems(good, types) == {}
    assert_template_ok(good, types)
    bad = {"Parameters": {"Idle": {"Type": "String"}}, "Resources": {"A": gadget, "B": {"Type": "X", "Properties": {"P": get_att("A", "Nope"), "Q": ref("Zed")}}}}
    assert set(find_all_problems(bad, types)) == {"references", "unused", "attributes"}
    assert set(find_all_problems(bad)) == {"references", "unused"}  # no types: the schema checks are skipped
    assert set(find_all_problems(bad, unused=False)) == {"references"}
    with pytest.raises(AssertionError, match=r"\[references\].*\n.*\[unused\] Parameters.Idle"):
        assert_template_ok(bad)
