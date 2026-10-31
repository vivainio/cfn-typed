"""A made-up state machine, ported to fragments with every state name kept (see docs/patterns/state-machines.md).

`original.json` is the machine as a template might hold it. `build()` here makes the same machine, state for state,
and `tests/test_state_machine_example.py` fails on any difference. Nothing in these files is from a real account.
"""

from typing import Any

from cfn_typed.asl import ChoiceRule, Definition, Exit, Fragment, catch, choice, retry, rule, step, wait

# --8<-- [start:policies]
WORKER = "arn:aws:lambda:${AWS::Region}:${AWS::AccountId}:function:acme-ledger-${Stage}-worker"
TRANSIENT = ["Lambda.ServiceException", "Lambda.AWSLambdaException", "Lambda.SdkClientException", "Lambda.TooManyRequestsException"]
RETRY_TRANSIENT, RETRY_ALL = [retry(*TRANSIENT)], [retry("States.ALL")]
# --8<-- [end:policies]

# --8<-- [start:builders]
SUCCEEDED, FAILED, ERROR = Exit("succeeded"), Exit("failed"), Exit("error")
# succeeded: the shared Succeed state. error: the shared Fail state. failed: this operation's own failure handler.


def task(next: str | None = None, *, retry: Any = RETRY_TRANSIENT, catch_to: str | None = FAILED, end: bool = False) -> dict[str, Any]:
    """A call to the worker Lambda. The retry set and where an error goes are the two things that differ."""
    state: dict[str, Any] = {"Type": "Task", "Resource": WORKER}
    if next:
        state["Next"] = next
    if end:
        state["End"] = True
    if retry:
        state["Retry"] = retry
    if catch_to:
        state["Catch"] = [catch(catch_to)]
    return state


def flag(variable: str, value: bool, next: str) -> ChoiceRule:
    return rule(variable, "BooleanEquals", value, next)


def status_loop(name: str, *, seconds: int | None = None, seconds_path: str | None = None, done: str, default: str = ERROR,
                catch_to: str = FAILED, wait_name: str | None = None, flag_name: str = "$.finished") -> dict[str, Any]:
    """Wait, ask the worker how it is going, and either go round again, move on to `done`, or give up at `default`."""
    wait_, check, verify = wait_name or f"Wait_{name}", f"Check_{name}", f"Verify_{name}"
    return {
        wait_: wait(check, seconds=seconds, seconds_path=seconds_path),
        check: task(verify, retry=RETRY_ALL, catch_to=catch_to),
        verify: choice(flag(flag_name, True, done), flag(flag_name, False, wait_), default=default),
    }
# --8<-- [end:builders]


# --8<-- [start:operations]
def import_invoices() -> Fragment:
    return Fragment("Start_ImportInvoices", {
        "Start_ImportInvoices": task("Wait_ImportStatus"),
        **status_loop("ImportStatus", seconds=30, done="Finalize_ImportInvoices"),
        "Finalize_ImportInvoices": task(SUCCEEDED),
        "Perform_ImportFailed": task(ERROR, retry=None, catch_to=None),  # the only handler with no retry and no catch
    }).wire("failed", "Perform_ImportFailed")


def reconcile_ledger() -> Fragment:
    return Fragment("Check_ReconcileTimings", {
        "Check_ReconcileTimings": choice(rule("$.start_time", "IsTimestamp", True, "Wait_StartReconcile"), default="Start_Reconcile"),
        "Wait_StartReconcile": wait("Start_Reconcile", timestamp_path="$.start_time"),
        "Start_Reconcile": task("Fetch_Accounts"),
        # The original catches this one into the *import* handler. Kept as it was, under its own exit name.
        "Fetch_Accounts": task("Map_Accounts", catch_to=Exit("import_failed")),
        "Map_Accounts": {
            "Type": "Map", "ItemsPath": "$.input.accounts", "MaxConcurrency": 5, "ResultPath": "$.accountResults",
            "Parameters": {"Account.$": "$$.Map.Item.Value", "Run.$": "$.run"},
            "Iterator": {"StartAt": "Reconcile_Account", "States": {"Reconcile_Account": task(end=True, retry=None, catch_to=None)}},
            "Next": "Wait_ReconcileStaus", "Retry": RETRY_TRANSIENT, "Catch": [catch(FAILED)],
        },
        # `Staus` is the original's spelling, and the status check catches into the shared failure state, not the handler.
        **status_loop("ReconcileStatus", seconds_path="$.wait_time", done="Finalize_Reconcile", default=FAILED,
                      catch_to=ERROR, wait_name="Wait_ReconcileStaus", flag_name="$.continue"),
        "Finalize_Reconcile": task(SUCCEEDED),
        "Perform_ReconcileFailed": task(ERROR, catch_to=ERROR),
    }).wire("failed", "Perform_ReconcileFailed").wire("import_failed", "Perform_ImportFailed")


def archive_reports() -> Fragment:
    return Fragment("Start_ArchiveReports", {
        "Start_ArchiveReports": task("Fan_Archive"),
        "Fan_Archive": {
            "Type": "Parallel", "Next": "Notify_Archive", "Retry": RETRY_TRANSIENT, "Catch": [catch(FAILED)],
            "Branches": [
                {"StartAt": "Render_Pdf", "States": {"Render_Pdf": task(end=True, retry=None, catch_to=None)}},
                {"StartAt": "Render_Csv", "States": {
                    "Render_Csv": task("Compress_Csv", retry=None, catch_to=None),
                    "Compress_Csv": task(end=True, retry=None, catch_to=None)}},
            ],
        },
        "Notify_Archive": task(SUCCEEDED),
        "Perform_ArchiveFailed": task(ERROR, catch_to=ERROR),
    }).wire("failed", "Perform_ArchiveFailed")
# --8<-- [end:operations]


# --8<-- [start:build]
ACTIONS = {"ImportInvoices": import_invoices, "ReconcileLedger": reconcile_ledger, "ArchiveReports": archive_reports}


def build() -> Definition:
    machine = Fragment("Route", {"Route": choice(*[rule("$.action", "StringEquals", a, Exit(a)) for a in ACTIONS], default=ERROR)})
    for action, operation in ACTIONS.items():
        machine = machine.wire(action, operation())
    return (
        machine.include(step("Common_Succeeded", {"Type": "Succeed"})).include(step("Common_Failed", {"Type": "Fail"}))
        .wire("succeeded", "Common_Succeeded").wire("error", "Common_Failed")
        .build(Comment="Ledger runner (a made-up machine for the docs)")
    )
# --8<-- [end:build]
