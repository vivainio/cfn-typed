"""The second pass over `port.py`: fix what the port showed was wrong, as a list of changes that can be reviewed."""

from typing import Any

from cfn_typed.asl import Definition, Fragment

from port import build as ported

# --8<-- [start:tidy]
RENAMES = {"Wait_ReconcileStaus": "Wait_ReconcileStatus"}


def own_handler(state: dict[str, Any]) -> dict[str, Any]:
    """Send these tasks' errors to the reconcile handler like the rest of the operation."""
    state["Catch"][0]["Next"] = "Perform_ReconcileFailed"
    return state


def build() -> Definition:
    machine = ported()
    return (
        Fragment(machine["StartAt"], machine["States"])
        .renamed(RENAMES)
        .map_states(own_handler, where=lambda s: s.get("Next") in ("Map_Accounts", "Verify_ReconcileStatus"))
        .build(Comment=machine.get("Comment", ""))
    )
# --8<-- [end:tidy]
