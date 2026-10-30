from typing import Any

import pytest

from cfn_typed import typegen as gen
from cfn_typed.constraints import find_constraint_problems
from cfn_typed.testing import assert_constraints_hold

GADGET: dict[str, Any] = {
    "typeName": "AWS::Foo::Gadget",
    "definitions": {
        "Rule": {
            "type": "object",
            "properties": {"Port": {"type": "integer", "minimum": 1, "maximum": 65535}, "Next": {"$ref": "#/definitions/Rule"}},
        },
    },
    "properties": {
        "Name": {"type": "string", "pattern": "^[a-z]+$", "minLength": 2, "maxLength": 5},
        "Mode": {"type": "string", "enum": ["fast", "slow"]},
        "Size": {"type": "integer", "minimum": 1, "maximum": 10},
        "Rules": {"type": "array", "minItems": 1, "maxItems": 2, "items": {"$ref": "#/definitions/Rule"}},
        "Labels": {"type": "object", "patternProperties": {".*": {"type": "string", "maxLength": 3}}},
        "Plain": {"type": "string"},
        "Dialect": {"type": "string", "pattern": "(?<n>x)\\p{L}"},  # not valid in Python's re
    },
}


def table(**kw: Any) -> dict[str, Any]:
    src = gen.render_module("AWS::Foo", [GADGET], overrides=gen.Overrides.of(**kw))
    ns: dict[str, Any] = {}
    exec(compile(src, "<gadget>", "exec"), ns)
    return ns["CONSTRAINTS"]


def problems(props: dict[str, Any], template: dict[str, Any] | None = None, **kw: Any) -> list[str]:
    t = {**(template or {}), "Resources": {"G": {"Type": "AWS::Foo::Gadget", "Properties": props}}}
    return find_constraint_problems(t, table(), **kw)


def test_generator_keeps_only_checkable_constraints_and_cuts_recursion() -> None:
    t = table()["AWS::Foo::Gadget"]
    assert t["Name"] == {"p": "^[a-z]+$", "l": 2, "L": 5}  # one-letter keys: see cfn_typed.constraints.SHORT
    assert "Plain" not in t and "Dialect" not in t  # nothing to check, and a pattern Python cannot compile
    assert t["Rules"]["T"]["P"]["Port"] == {"m": 1, "M": 65535}
    assert "Next" not in t["Rules"]["T"]["P"]  # Rule inside Rule adds nothing the outer one doesn't
    assert t["Labels"]["V"] == {"L": 3}


def test_unconstrained_drops_a_property_and_no_constraints_drops_the_table() -> None:
    assert "Name" not in table(unconstrained=["AWS::Foo::Gadget.Name"])["AWS::Foo::Gadget"]
    assert "CONSTRAINTS" not in gen.render_module("AWS::Foo", [GADGET], constraints=False)


def test_valid_values_pass() -> None:
    assert problems({"Name": "abc", "Mode": "fast", "Size": 3, "Rules": [{"Port": 443}], "Labels": {"a": "xyz"}, "Plain": "anything"}) == []


def test_each_kind_of_constraint_is_reported_with_its_path() -> None:
    found = problems({"Name": "ABCDEFG", "Mode": "warp", "Size": 11, "Rules": [{"Port": 0}, {"Port": 1}, {"Port": 2}], "Labels": {"k": "toolong"}})
    text = "\n".join(found)
    assert "Resources.G.Properties.Name: 'ABCDEFG' is longer than the maximum length 5" in text
    assert "does not match the pattern '^[a-z]+$'" in text
    assert "Resources.G.Properties.Mode: 'warp' is not one of 'fast', 'slow'" in text
    assert "Resources.G.Properties.Size: 11 is greater than the maximum of 10" in text
    assert "Resources.G.Properties.Rules[0].Port: 0 is less than the minimum of 1" in text
    assert "Resources.G.Properties.Rules: has 3 items, more than the maximum of 2" in text
    assert "Resources.G.Properties.Labels.k: 'toolong' is longer than the maximum length 3" in text


def test_numeric_strings_are_checked_as_numbers_and_enum_ints_match_their_strings() -> None:
    assert problems({"Size": "11"}) == ["Resources.G.Properties.Size: '11' is greater than the maximum of 10"]
    assert problems({"Size": "3"}) == []


def test_values_that_only_deploy_time_decides_are_skipped() -> None:
    props = {"Name": {"Ref": "Queue"}, "Mode": {"Fn::GetAtt": ["Q", "Arn"]}, "Size": {"Ref": "AWS::NoValue"}, "Plain": "{{resolve:ssm:/x}}"}
    ssm = {"Parameters": {"Ssm": {"Type": "AWS::SSM::Parameter::Value<String>", "Default": "/not/the/value"}}}
    assert problems({**props, "Labels": {"a": {"Ref": "Ssm"}}}, ssm) == []


def test_ref_to_a_parameter_checks_allowed_values_else_the_default() -> None:
    params = {"Parameters": {"M": {"Type": "String", "AllowedValues": ["fast", "warp"]}, "S": {"Type": "Number", "Default": 99}}}
    found = problems({"Mode": {"Ref": "M"}, "Size": {"Ref": "S"}}, params)
    assert found == [
        "Resources.G.Properties.Mode: 'warp' is not one of 'fast', 'slow' (Ref M, allowed value)",
        "Resources.G.Properties.Size: 99 is greater than the maximum of 10 (Ref S, default)",
    ]
    assert problems({"Size": {"Ref": "S"}}, params, defaults=False) == []


def test_if_checks_both_branches_and_skips_no_value() -> None:
    found = problems({"Mode": {"Fn::If": ["C", "warp", "fast"]}, "Size": {"Fn::If": ["C", 99, {"Ref": "AWS::NoValue"}]}})
    assert [f.split(": ")[0] for f in found] == ["Resources.G.Properties.Mode", "Resources.G.Properties.Size"]
    assert "(Fn::If true branch)" in found[0]


def test_find_in_map_follows_literal_keys_and_every_entry_under_an_unknown_one() -> None:
    maps = {"Mappings": {"Sizes": {"dev": {"N": 2}, "prod": {"N": 50}}}}
    literal = problems({"Size": {"Fn::FindInMap": ["Sizes", "dev", "N"]}}, maps)
    assert literal == []
    unknown = problems({"Size": {"Fn::FindInMap": ["Sizes", {"Ref": "AWS::Region"}, "N"]}}, maps)
    assert unknown == ["Resources.G.Properties.Size: 50 is greater than the maximum of 10 (Fn::FindInMap Sizes/prod/N)"]


def test_sub_join_select_and_split_are_evaluated_when_their_pieces_are_known() -> None:
    params = {"Parameters": {"Stage": {"Type": "String", "AllowedValues": ["dev", "production"]}}}
    found = problems({"Name": {"Fn::Sub": ["${Stage}", {}]}, "Labels": {
        "a": {"Fn::Join": ["-", ["ab", {"Ref": "Stage"}]]},
        "b": {"Fn::Select": [1, {"Fn::Split": [",", "x,yyyy"]}]},
        "c": {"Fn::Sub": "${AWS::Region}"},  # unknown, skipped
    }}, params)
    text = "\n".join(found)
    assert "Name: 'production' is longer than the maximum length 5 (Fn::Sub)" in text
    assert "Labels.a: 'ab-production'" in text and "Labels.b: 'yyyy'" in text and "Labels.c" not in text


def test_a_generated_package_without_constraints_is_an_error_not_silence() -> None:
    import sys
    import types

    pkg = types.ModuleType("pkg_no_constraints")
    pkg.__path__ = []  # type: ignore[attr-defined]
    mod = types.ModuleType("pkg_no_constraints.foo")
    sys.modules.update({"pkg_no_constraints": pkg, "pkg_no_constraints.foo": mod})
    try:
        with pytest.raises(ValueError, match="no-constraints"):
            find_constraint_problems({"Resources": {"G": {"Type": "AWS::Foo::Gadget", "Properties": {}}}}, pkg)
    finally:
        del sys.modules["pkg_no_constraints"], sys.modules["pkg_no_constraints.foo"]


def test_assert_constraints_hold_lists_every_problem() -> None:
    template = {"Resources": {"G": {"Type": "AWS::Foo::Gadget", "Properties": {"Mode": "warp", "Size": 0}}}}
    with pytest.raises(AssertionError, match="Mode.*\n.*Size"):
        assert_constraints_hold(template, table())
    assert_constraints_hold({"Resources": {}}, table())



def test_repeated_nodes_and_long_values_are_written_once() -> None:
    long_enum = [f"value-number-{i}" for i in range(5)]
    shared = {"type": "object", "properties": {"Kind": {"type": "string", "enum": long_enum}, "Other": {"type": "string", "enum": long_enum}}}
    schema = {"typeName": "AWS::Foo::Twin", "definitions": {"Shared": shared},
              "properties": {"A": {"$ref": "#/definitions/Shared"}, "B": {"$ref": "#/definitions/Shared"}}}
    src = gen.render_module("AWS::Foo", [schema])
    assert src.count("value-number-0") == 1  # the enum, once, though four properties use it
    assert src.count("_c") >= 2
    ns: dict[str, Any] = {}
    exec(compile(src, "<twin>", "exec"), ns)
    twin = ns["CONSTRAINTS"]["AWS::Foo::Twin"]
    assert twin["A"] is twin["B"] and twin["A"]["P"]["Kind"]["e"] == long_enum
    assert " " not in src.split("CONSTRAINTS:")[1]  # compact: no spaces in the table
