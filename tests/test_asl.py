"""State machine checks. The definitions are made up for the tests: none comes from a real account."""

import copy
from typing import Any

import pytest

from cfn_typed import sub
from cfn_typed.asl import Definition, find_asl_problems, find_state_machine_problems
from cfn_typed.checks import find_all_problems
from cfn_typed.testing import assert_state_machine_valid, assert_state_machines_valid

LAMBDA = "arn:aws:lambda:eu-north-1:000000000000:function:example"


def good() -> Definition:
    return {
        "StartAt": "Fetch",
        "States": {
            "Fetch": {
                "Type": "Task", "Resource": LAMBDA, "Next": "Check",
                "Retry": [{"ErrorEquals": ["Lambda.ServiceException"], "IntervalSeconds": 2, "MaxAttempts": 3, "BackoffRate": 2.0}],
                "Catch": [{"ErrorEquals": ["States.ALL"], "Next": "Failed", "ResultPath": "$.error"}],
            },
            "Check": {"Type": "Choice", "Choices": [{"Variable": "$.done", "BooleanEquals": True, "Next": "Done"}], "Default": "Pause"},
            "Pause": {"Type": "Wait", "SecondsPath": "$.delay", "Next": "Fetch"},
            "Done": {"Type": "Succeed"},
            "Failed": {"Type": "Fail", "Error": "Broken"},
        },
    }


def problems(edit: Any) -> list[str]:
    d: Any = copy.deepcopy(good())
    edit(d["States"])
    return find_asl_problems(d)


def test_a_sound_machine_has_no_problems() -> None:
    assert find_asl_problems(good()) == []
    assert_state_machine_valid(good())


def test_dangling_transitions_are_named() -> None:
    def edit(s: Any) -> None:
        s["Fetch"]["Next"] = "Chekc"
        s["Fetch"]["Catch"][0]["Next"] = "Oops"
        s["Check"]["Default"] = "Nowhere"
        s["Check"]["Choices"][0]["Next"] = "Gone"

    found = problems(edit)
    for name in ("'Chekc'", "'Oops'", "'Nowhere'", "'Gone'"):
        assert any(name in p for p in found), name


def test_start_at_must_exist() -> None:
    d: Any = good()
    d["StartAt"] = "Nope"
    assert any("StartAt" in p and "'Nope'" in p for p in find_asl_problems(d))


def test_next_and_end() -> None:
    found = problems(lambda s: s["Pause"].update(End=True))
    assert any("Pause" in p and "has both" in p for p in found)
    found = problems(lambda s: s["Pause"].pop("Next"))
    assert any("Pause" in p and "has neither" in p for p in found)
    found = problems(lambda s: s["Done"].update(End=True))
    assert any("Done" in p and "no Next or End" in p for p in found)
    found = problems(lambda s: s["Check"].update(Next="Done"))
    assert any("Check" in p and "no Next or End" in p for p in found)


def test_unreachable_state_and_loop_without_exit() -> None:
    found = problems(lambda s: s.update(Orphan={"Type": "Succeed"}))
    assert any("Orphan" in p and "unreachable" in p for p in found)
    d: Any = {"StartAt": "A", "States": {"A": {"Type": "Pass", "Next": "B"}, "B": {"Type": "Pass", "Next": "A"}}}
    assert {p.split(":")[0] for p in find_asl_problems(d) if "reaches an end" in p} == {"States.A", "States.B"}


def test_catch_target_counts_as_reachable() -> None:
    assert not any("Failed" in p for p in find_asl_problems(good()))
    found = problems(lambda s: s["Fetch"]["Catch"][0].update(Next="Done"))
    assert any("Failed" in p and "unreachable" in p for p in found)


def test_retry_and_catch_rules() -> None:
    def edit(s: Any) -> None:
        s["Fetch"]["Retry"] = [
            {"ErrorEquals": ["States.ALL"], "MaxAttempts": 2},
            {"ErrorEquals": ["States.Typo"], "IntervalSeconds": 0, "BackoffRate": 0.5},
            {"ErrorEquals": ["States.ALL", "Boom"]},
            {"ErrorEquals": []},
        ]

    text = "\n".join(problems(edit))
    assert "must be in the last entry" in text
    assert "'States.Typo' is not a Step Functions error name" in text
    assert "IntervalSeconds is 0" in text
    assert "BackoffRate is 0.5" in text
    assert "must be the only entry" in text
    assert "non-empty list" in text


def test_retry_on_a_choice_is_refused() -> None:
    found = problems(lambda s: s["Check"].update(Retry=[]))
    assert any("Retry is only for" in p for p in found)


def test_wait_needs_exactly_one_duration() -> None:
    assert any("exactly one of" in p for p in problems(lambda s: s["Pause"].update(Seconds=5)))
    assert any("exactly one of" in p for p in problems(lambda s: s["Pause"].pop("SecondsPath")))


def test_paths_start_with_dollar_but_not_under_jsonata() -> None:
    found = problems(lambda s: (s["Pause"].update(SecondsPath="delay"), s["Check"]["Choices"][0].update(Variable="done")))
    assert any("Pause.SecondsPath" in p for p in found) and any("Choices[0].Variable" in p for p in found)
    assert problems(lambda s: s["Fetch"].update(ResultPath=None)) == []  # null is a legal ResultPath
    assert any("Fetch.OutputPath" in p for p in problems(lambda s: s["Fetch"].update(InputPath=None, OutputPath="x")))

    d: Any = good()
    d["QueryLanguage"] = "JSONata"
    d["States"]["Pause"]["SecondsPath"] = "delay"
    assert find_asl_problems(d) == []


def test_nested_choice_rules_are_checked() -> None:
    def edit(s: Any) -> None:
        s["Check"]["Choices"][0] = {"Not": {"Or": [{"Variable": "x", "IsNull": True}]}, "Next": "Done"}

    assert any("Choices[0].Not.Or[0].Variable" in p for p in problems(edit))


def test_parallel_and_map_branches_are_their_own_scope() -> None:
    d: Any = good()
    d["States"]["Fetch"] = {
        "Type": "Parallel", "Next": "Check",
        "Branches": [
            {"StartAt": "Inner", "States": {"Inner": {"Type": "Pass", "Next": "Check"}}},  # Check is outside the branch
        ],
    }
    found = find_asl_problems(d)
    assert any("Branches[0].Inner" in p and "'Check'" in p for p in found)

    d["States"]["Fetch"] = {
        "Type": "Map", "Next": "Check",
        "ItemProcessor": {"StartAt": "Pause", "States": {"Pause": {"Type": "Succeed"}}},  # name already used outside
    }
    assert any("States.Pause" in p and "also used at States.Fetch.ItemProcessor.Pause" in p for p in find_asl_problems(d))

    fine: Definition = {
        "StartAt": "Fan",
        "States": {
            "Fan": {"Type": "Map", "Next": "Done", "ItemProcessor": {"StartAt": "Inner", "States": {"Inner": {"Type": "Succeed"}}}},
            "Done": {"Type": "Succeed"},
        },
    }
    assert find_asl_problems(fine) == []


def test_names_and_types_and_size() -> None:
    long = "x" * 81
    d: Any = {"StartAt": long, "States": {long: {"Type": "Succeed"}, "B": {"Type": "Nonsense"}}}
    text = "\n".join(find_asl_problems(d))
    assert "81 characters" in text and "'Nonsense'" in text
    big: Any = {"StartAt": "A", "States": {"A": {"Type": "Pass", "End": True, "Result": "x" * 1_048_576}}}
    assert any("allows at most" in p for p in find_asl_problems(big))


def test_assert_lists_every_problem() -> None:
    d: Any = good()
    d["States"]["Fetch"]["Next"] = "Missing"
    with pytest.raises(AssertionError, match="Missing"):
        assert_state_machine_valid(d)


def machine_template(**props: Any) -> dict[str, Any]:
    return {"Resources": {"Machine": {"Type": "AWS::StepFunctions::StateMachine", "Properties": {"RoleArn": "r", **props}}}}


def test_template_check_reads_definition_and_definition_string() -> None:
    bad: Any = copy.deepcopy(good())
    bad["States"]["Pause"]["Next"] = "Missing"
    import json

    for props in ({"Definition": bad}, {"DefinitionString": json.dumps(bad)}, {"DefinitionString": sub(json.dumps(bad).replace("example", "${Fn}"))}):
        found = find_state_machine_problems(machine_template(**props))
        assert found and all(p.startswith("Machine.States.") for p in found) and "Missing" in found[0], props
        assert "asl" in find_all_problems(machine_template(**props))
        with pytest.raises(AssertionError, match="Machine"):
            assert_state_machines_valid(machine_template(**props))
    assert find_state_machine_problems(machine_template(Definition=good())) == []


def test_template_check_skips_what_it_cannot_read() -> None:
    assert find_state_machine_problems(machine_template(DefinitionString={"Fn::Join": ["", ["{", "}"]]})) == []
    assert find_state_machine_problems(machine_template(DefinitionString="{not json")) == ["Machine: DefinitionString is not valid JSON (Expecting property name enclosed in double quotes: line 1 column 2 (char 1))"]
