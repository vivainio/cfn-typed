"""examples/state_machine: the made-up machine the 'Working with state machines' page walks through."""

import importlib
import json
import sys
from typing import Any
from pathlib import Path

import pytest

from cfn_typed.asl import Fragment, find_asl_problems, find_machine_differences, to_mermaid
from cfn_typed.testing import assert_same_machine

EXAMPLE = Path(__file__).parent.parent / "examples" / "state_machine"


@pytest.fixture(autouse=True)
def example_on_path(monkeypatch):
    monkeypatch.syspath_prepend(str(EXAMPLE))
    for name in ("port", "tidy", "survey"):
        sys.modules.pop(name, None)
    yield
    for name in ("port", "tidy", "survey"):
        sys.modules.pop(name, None)


def load(name: str) -> Any:
    return importlib.import_module(name)


def original() -> dict:
    return json.loads((EXAMPLE / "original.json").read_text())


def test_the_original_is_a_sound_machine() -> None:
    assert find_asl_problems(original()) == []


def test_the_port_is_the_original_state_for_state() -> None:
    assert_same_machine(load('port').build(), original())


def test_the_tidy_pass_changes_exactly_what_it_says() -> None:
    renamed = Fragment(original()["StartAt"], original()["States"]).renamed(load('tidy').RENAMES).build(Comment=original()["Comment"])
    assert sorted(find_machine_differences(load('tidy').build(), renamed)) == [
        'States.Check_ReconcileStatus.Catch[0].Next: "Perform_ReconcileFailed", expected "Common_Failed"',
        'States.Fetch_Accounts.Catch[0].Next: "Perform_ReconcileFailed", expected "Perform_ImportFailed"',
    ]
    assert "Wait_ReconcileStatus" in load('tidy').build()["States"] and "Wait_ReconcileStaus" not in load('tidy').build()["States"]


def test_a_partial_port_can_be_compared_state_by_state() -> None:
    fragment = load('port').import_invoices().wire("succeeded", "Common_Succeeded").wire("error", "Common_Failed")
    expected = {name: original()["States"][name] for name in fragment.states}
    assert fragment.states == expected


def test_the_survey_finds_the_quirks() -> None:
    text = "\n".join(load('survey').survey(original()))
    assert "Wait_ImportStatus" in text and "Wait_ReconcileStaus" in text
    assert "Perform_ImportFailed" in text and "Common_Failed x" in text


def test_the_diagram_has_every_operation() -> None:
    text = to_mermaid(original())
    assert text.startswith("stateDiagram-v2") and "Fan_Archive" in text and "<<choice>>" in text


def test_the_skill_skeleton_runs() -> None:
    import re

    text = (Path(__file__).parent.parent / "skills" / "cfn-typed" / "resources" / "state-machines.md").read_text()
    namespace: dict[str, Any] = {"WORKER_ARN": "arn:${AWS::Region}:example"}
    exec(re.findall(r"```python\n(.*?)```", text, re.S)[0], namespace)
    assert find_asl_problems(namespace["machine"]) == []
