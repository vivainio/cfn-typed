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


# --- fragments -----------------------------------------------------------------------------------------------------

from cfn_typed.asl import Exit, Fragment, chain, find_machine_differences, step, to_mermaid  # noqa: E402
from cfn_typed.testing import assert_same_machine  # noqa: E402


def task(**more: Any) -> Any:
    return {"Type": "Task", "Resource": LAMBDA, **more}


def poll() -> Fragment:
    """Wait, run, check; leaves through `done` and `failed`, and loops back to the wait by itself."""
    return Fragment("Wait", {
        "Wait": {"Type": "Wait", "SecondsPath": "$.delay", "Next": "Run"},
        "Run": task(Next="Check", Catch=[{"ErrorEquals": ["States.ALL"], "Next": Exit("failed")}]),
        "Check": {"Type": "Choice", "Choices": [{"Variable": "$.ok", "BooleanEquals": True, "Next": Exit("done")}], "Default": "Wait"},
    })


def test_exits_are_found_and_a_plain_task_gets_next() -> None:
    assert poll().exits == {"done", "failed"}
    assert step("A", task()).exits == {"next"}
    assert step("A", {"Type": "Succeed"}).exits == frozenset()
    assert step("A", task(End=True)).exits == frozenset()


def test_chain_wires_next_and_build_is_checked() -> None:
    machine: Any = chain(step("Prepare", task()), step("Finish", task())).end().build(Comment="demo")
    assert machine["Comment"] == "demo" and machine["StartAt"] == "Prepare"
    assert machine["States"]["Prepare"]["Next"] == "Finish" and machine["States"]["Finish"] == task(End=True)
    assert not any(isinstance(s.get("Next"), Exit) for s in machine["States"].values())


def test_wire_to_a_fragment_or_a_name_and_shared_exits() -> None:
    ok, bad = step("Ok", {"Type": "Succeed"}), step("Bad", {"Type": "Fail"})
    machine: Any = poll().wire("done", ok).wire("failed", bad).build()
    assert machine["States"]["Check"]["Choices"][0]["Next"] == "Ok" and machine["States"]["Run"]["Catch"][0]["Next"] == "Bad"
    # a name that lives elsewhere in the machine, and two fragments leaving through the same `failed`
    two = poll().prefixed("A_").wire("done", poll().prefixed("B_"))
    assert two.exits == {"done", "failed"}
    assert two.wire("failed", "Handler").exits == {"done"}
    assert "Handler" == two.wire("failed", "Handler").states["B_Run"]["Catch"][0]["Next"] == two.wire("failed", "Handler").states["A_Run"]["Catch"][0]["Next"]


def test_unwired_exits_and_unknown_exit_names_are_refused() -> None:
    with pytest.raises(ValueError, match="unwired exits: done, failed"):
        poll().build()
    with pytest.raises(ValueError, match=r"no exit 'nope'; the exits are \['done', 'failed'\]"):
        poll().wire("nope", "X")


def test_build_refuses_an_unsound_graph() -> None:
    with pytest.raises(ValueError, match="unreachable"):
        step("A", {"Type": "Succeed"}).include(step("B", {"Type": "Succeed"})).build()
    with pytest.raises(ValueError, match="'Missing'"):
        step("A", task(Next="Missing")).build()


def test_name_clash_asks_for_a_prefix() -> None:
    with pytest.raises(ValueError, match="'Wait'.*prefixed"):
        poll().wire("done", poll())


def test_prefixed_renames_states_and_internal_references_only() -> None:
    p = poll().wire("failed", "Common_Failed").prefixed("Tenant_")
    assert p.start == "Tenant_Wait" and set(p.states) == {"Tenant_Wait", "Tenant_Run", "Tenant_Check"}
    assert p.states["Tenant_Wait"]["Next"] == "Tenant_Run"
    assert p.states["Tenant_Check"]["Default"] == "Tenant_Wait"
    assert p.states["Tenant_Run"]["Catch"][0]["Next"] == "Common_Failed"  # not in the fragment: left alone
    assert isinstance(p.states["Tenant_Check"]["Choices"][0]["Next"], Exit) and p.exits == {"done"}


def test_prefixed_reaches_into_nested_scopes() -> None:
    inner = {"StartAt": "In", "States": {"In": {"Type": "Pass", "Next": "Out"}, "Out": {"Type": "Succeed"}}}
    f = Fragment("Fan", {"Fan": {"Type": "Parallel", "Branches": [inner], "End": True},
                          "Each": {"Type": "Map", "ItemProcessor": inner, "End": True}}).prefixed("X_")
    branch = f.states["X_Fan"]["Branches"][0]
    assert branch["StartAt"] == "X_In" and branch["States"]["X_In"]["Next"] == "X_Out"
    assert f.states["X_Each"]["ItemProcessor"]["StartAt"] == "X_In"
    assert inner["StartAt"] == "In"  # the original is untouched


def test_the_same_pattern_twice_needs_the_prefix() -> None:
    both: Any = (
        poll().prefixed("A_").wire("done", poll().prefixed("B_"))
        .wire("done", step("Done", {"Type": "Succeed"}))
        .wire("failed", step("Failed", {"Type": "Fail"}))
        .build()
    )
    assert find_asl_problems(both) == []
    assert both["States"]["A_Check"]["Choices"][0]["Next"] == "B_Wait" and both["States"]["B_Check"]["Choices"][0]["Next"] == "Done"


def test_map_states_applies_a_policy_to_matching_states_only() -> None:
    def add_catch(state: dict[str, Any]) -> dict[str, Any]:
        state["Catch"] = [{"ErrorEquals": ["States.ALL"], "Next": "Boom", "ResultPath": "$.error"}]
        return state

    f = chain(step("A", task()), step("W", {"Type": "Wait", "Seconds": 1}), step("B", task())).map_states(add_catch, where="Task")
    assert f.states["A"]["Catch"][0]["Next"] == "Boom" and "Catch" not in f.states["W"]
    only_b = f.map_states(lambda s: {**s, "TimeoutSeconds": 5}, where=lambda s: s.get("Next") == Exit("next"))
    assert "TimeoutSeconds" in only_b.states["B"] and "TimeoutSeconds" not in only_b.states["A"]
    assert "Catch" not in step("A", task()).states["A"]  # fragments do not change


def test_end_only_for_plain_next() -> None:
    assert step("A", task()).end().states["A"] == task(End=True)
    with pytest.raises(ValueError, match="cannot be an End"):
        poll().end("done")


def test_include_adds_states_and_their_exits() -> None:
    f = poll().include(step("Common_Failed", {"Type": "Fail"})).wire("failed", "Common_Failed")
    assert "Common_Failed" in f.states and f.start == "Wait"


def test_same_machine_comparison() -> None:
    a = good()
    b: Any = copy.deepcopy(a)
    assert find_machine_differences(a, b) == [] and assert_same_machine(a, b) is None
    assert find_machine_differences(a, dict(reversed(list(b.items())))) == []  # key order is not a difference
    b["States"]["Fetch"]["Retry"][0]["MaxAttempts"] = 9
    b["States"]["Extra"] = {"Type": "Succeed"}
    del b["States"]["Done"]
    b["States"]["Check"]["Choices"].append({"Variable": "$.x", "IsNull": True, "Next": "Done"})
    found = find_machine_differences(a, b)
    assert "States.Fetch.Retry[0].MaxAttempts: 3, expected 9" in found
    assert any(p.startswith("States.Extra: missing") for p in found)
    assert any(p.startswith("States.Done: not expected") for p in found)
    assert "States.Check.Choices: 1 items, expected 2" in found
    with pytest.raises(AssertionError, match="MaxAttempts"):
        assert_same_machine(a, b)
    assert find_machine_differences({"a": 1}, {"a": True}) == ["a: 1, expected true"]
    assert find_machine_differences({"a": 1}, {"a": 1.0}) == []


def test_fragments_rebuild_a_machine_exactly() -> None:
    """The refactor test: the machine written out in full equals the one made of fragments."""
    full: Any = {
        "StartAt": "Prepare",
        "States": {
            "Prepare": task(Next="Wait"),
            "Wait": {"Type": "Wait", "SecondsPath": "$.delay", "Next": "Run"},
            "Run": task(Next="Check", Catch=[{"ErrorEquals": ["States.ALL"], "Next": "Failed"}]),
            "Check": {"Type": "Choice", "Choices": [{"Variable": "$.ok", "BooleanEquals": True, "Next": "Done"}], "Default": "Wait"},
            "Done": {"Type": "Succeed"},
            "Failed": {"Type": "Fail"},
        },
    }
    built = (
        step("Prepare", task()).then(poll())
        .wire("done", step("Done", {"Type": "Succeed"})).wire("failed", step("Failed", {"Type": "Fail"})).build()
    )
    assert_same_machine(built, full)


def test_mermaid_draws_every_kind_of_edge() -> None:
    d: Any = good()
    d["States"]["Fan"] = {"Type": "Parallel", "End": True, "Branches": [{"StartAt": "A", "States": {"A": {"Type": "Succeed"}}}, {"StartAt": "B", "States": {"B": {"Type": "Succeed"}}}]}
    text = to_mermaid(d)
    assert text.startswith("stateDiagram-v2\n") and "<<choice>>" in text and ": catch" in text and ": default" in text
    assert "[*] -->" in text and text.count("--\n") == 1 and 'state "Fan"' in text
