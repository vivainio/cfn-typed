from datetime import date
from typing import Any

import pytest

from cfn_typed import find_in_map, ref
from cfn_typed.checks import find_all_problems
from cfn_typed.lifecycle import find_lifecycle_problems
from cfn_typed.testing import assert_runtimes_supported, assert_template_ok, assert_values_valid
from cfn_typed.values import find_value_problems


def fn(runtime: Any, **extra: Any) -> dict[str, Any]:
    return {"Resources": {"F": {"Type": "AWS::Lambda::Function", "Properties": {"Runtime": runtime}}}, **extra}


def test_runtime_dates_decide_what_is_reported() -> None:
    soon, after_dep, create_blocked = date(2025, 1, 1), date(2025, 6, 1), date(2027, 9, 1)
    assert find_lifecycle_problems(fn("python3.13"), today=date(2020, 1, 1)) == []  # not deprecated yet
    assert find_lifecycle_problems(fn("provided.custom"), today=soon) == []  # not a runtime it knows
    p = find_lifecycle_problems(fn("python3.8"), today=after_dep)
    assert len(p) == 1 and "Resources.F.Properties.Runtime: 'python3.8' is deprecated since" in p[0] and "blocked from" in p[0]
    blocked = find_lifecycle_problems(fn("python3.8"), today=create_blocked)
    assert "can no longer be" in blocked[0]


def test_runtime_is_followed_through_parameters_and_maps() -> None:
    params = {"Parameters": {"Rt": {"Type": "String", "AllowedValues": ["python3.13", "python2.7"]}}}
    p = find_lifecycle_problems(fn(ref("Rt"), **params), today=date(2026, 6, 1))
    assert len(p) == 1 and "'python2.7'" in p[0]
    assert find_lifecycle_problems(fn(ref("Rt"), **params), today=date(2026, 6, 1), defaults=False)  # AllowedValues still count
    with pytest.raises(AssertionError, match="deprecated Lambda runtimes"):
        assert_runtimes_supported(fn("python2.7"), today=date(2026, 6, 1))


def test_find_in_map_keys_must_exist() -> None:
    maps = {"Mappings": {"Sizes": {"dev": {"n": 1}, "prod": {"n": 2}}}, "Parameters": {"Stage": {"Type": "String", "AllowedValues": ["dev", "prod", "qa"]}}}
    t = {**maps, "Resources": {"R": {"Type": "X", "Properties": {
        "Ok": find_in_map("Sizes", "dev", "n"), "BadFirst": find_in_map("Sizes", "test", "n"), "BadSecond": find_in_map("Sizes", "dev", "m"),
        "ByParam": find_in_map("Sizes", ref("Stage"), "n"),
        "WithDefault": {"Fn::FindInMap": ["Sizes", "test", "n", {"DefaultValue": 0}]},
        "Unknown": find_in_map("Nope", "a", "b"),
    }}}}
    text = "\n".join(find_value_problems(t))
    assert "BadFirst: Fn::FindInMap key 'test' is not in mapping 'Sizes'" in text
    assert "BadSecond: Fn::FindInMap key 'm' is not in Sizes/dev" in text
    assert "ByParam: Fn::FindInMap key 'qa' is not in mapping 'Sizes'" in text and "(" in text
    assert text.count("\n") == 2  # three problems; Ok, WithDefault and a mapping that does not exist (references reports it) add nothing


def test_select_index_must_be_inside_the_list() -> None:
    t = {"Resources": {"R": {"Type": "X", "Properties": {"A": {"Fn::Select": [2, ["a", "b"]]}, "B": {"Fn::Select": ["1", ["a", "b"]]}, "C": {"Fn::Select": [0, {"Fn::GetAZs": ""}]}}}}}
    assert find_value_problems(t) == ["Resources.R.Properties.A: Fn::Select index 2 is outside the list, which has 2 items"]


def test_parameter_defaults_must_satisfy_their_own_constraints() -> None:
    t = {"Parameters": {
        "Mode": {"Type": "String", "Default": "x", "AllowedValues": ["a", "b"]},
        "Name": {"Type": "String", "Default": "Ab", "AllowedPattern": "[a-z]+", "MinLength": 3},
        "Count": {"Type": "Number", "Default": "12", "MinValue": 1, "MaxValue": 10},
        "Word": {"Type": "Number", "Default": "x"},
        "Fine": {"Type": "String", "Default": "abc", "AllowedPattern": "[a-z]+", "MaxLength": 5},
        "NoDefault": {"Type": "String", "AllowedValues": ["a"]},
    }, "Resources": {}}
    found = find_value_problems(t)
    assert [p.split(":")[0] for p in found] == ["Parameters.Mode.Default", "Parameters.Name.Default", "Parameters.Name.Default", "Parameters.Count.Default", "Parameters.Word.Default"]


def test_all_in_one_includes_both() -> None:
    t = fn("python2.7", Parameters={"P": {"Type": "String", "Default": "x", "AllowedValues": ["y"]}})
    t["Parameters"]["P"]["Description"] = "used"
    assert {"values", "lifecycle"} <= set(find_all_problems(t, today=date(2026, 6, 1)))
    with pytest.raises(AssertionError, match=r"\[lifecycle\]"):
        assert_template_ok(t, today=date(2026, 6, 1))
    with pytest.raises(AssertionError, match="wrong"):
        assert_values_valid(t)
