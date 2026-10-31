"""Amazon States Language: typed states, and a check of the state graph.

    from cfn_typed.asl import Definition, TaskState, find_asl_problems

    definition: Definition = {
        "StartAt": "Fetch",
        "States": {
            "Fetch": {"Type": "Task", "Resource": fn_arn, "Next": "Done"},
            "Done": {"Type": "Succeed"},
        },
    }
    find_asl_problems(definition)   # [] when the graph is sound

`Definition` and the state types are closed `TypedDict`s, so the type checker rejects a misspelled key, a state without
its `Type`, or a `Choice` with a `Next`. They are the shape the ASL spec documents, no more: how a machine is put
together (a polling loop, a shared retry policy) is ordinary Python on top of them, and is not in here.

`find_asl_problems` reports what Step Functions only tells you at deploy time, or at run time:

- `StartAt`, `Next`, `Default`, `Choices[].Next` and `Catch[].Next` name a state in the same scope (a `Parallel` branch or
  a `Map` item processor is its own scope; no transition crosses it);
- state names are unique across the whole machine and at most 80 characters;
- each state has exactly one of `Next` and `End`, except `Choice`, `Succeed` and `Fail`, which have neither;
- no state is unreachable, and every reachable state can reach an end (a loop with no way out is reported);
- `Retry` and `Catch` have a non-empty `ErrorEquals` of known `States.*` names, `States.ALL` alone and last, and the
  numeric fields in range;
- a `Wait` has exactly one of `Seconds`, `Timestamp`, `SecondsPath` and `TimestampPath`;
- path fields (`InputPath`, `ResultPath`, `Variable`, ...) start with `$` (not checked under `QueryLanguage: JSONata`);
- the definition is within the 1 MB limit.

Intrinsics (`Fn::Sub` and the like) are skipped wherever a plain value is expected, so the check also works on a
definition inside a template. `cfn_typed.checks.find_all_problems` runs it on every `Definition` it finds.
"""

import json
from collections import deque
from collections.abc import Mapping, Sequence
from typing import Any, Literal, NotRequired

from typing_extensions import TypedDict

from cfn_typed.intrinsics import Expr

DEFINITION_BYTES = 1_048_576
STATE_NAME_CHARS = 80
# The error names Step Functions defines. Any other `States.` name is a typo.
STATES_ERRORS = frozenset(
    "States." + name
    for name in (
        "ALL", "DataLimitExceeded", "ExceedToleratedFailureThreshold", "HeartbeatTimeout", "IntrinsicFailure",
        "ItemReaderFailed", "NoChoiceMatched", "ParameterPathFailure", "Permissions", "ResultPathMatchFailure",
        "ResultWriterFailed", "Runtime", "TaskFailed", "Timeout",
    )
)
STATE_TYPES = frozenset({"Task", "Pass", "Choice", "Wait", "Succeed", "Fail", "Parallel", "Map"})
_PATH_FIELDS = (
    "InputPath", "OutputPath", "ResultPath", "ItemsPath", "SecondsPath", "TimestampPath", "HeartbeatSecondsPath",
    "TimeoutSecondsPath",
)
_NULLABLE_PATHS = frozenset({"InputPath", "OutputPath", "ResultPath"})  # `null` means "nothing" for these
_WAIT_FIELDS = ("Seconds", "Timestamp", "SecondsPath", "TimestampPath")

type QueryLanguage = Literal["JSONPath", "JSONata"]


class Retrier(TypedDict, closed=True):
    ErrorEquals: list[str]
    IntervalSeconds: NotRequired[int]
    MaxAttempts: NotRequired[int]
    BackoffRate: NotRequired[float]
    MaxDelaySeconds: NotRequired[int]
    JitterStrategy: NotRequired[Literal["FULL", "NONE"]]


class Catcher(TypedDict, closed=True):
    ErrorEquals: list[str]
    Next: str
    ResultPath: NotRequired[str | None]
    Output: NotRequired[Any]


class TaskState(TypedDict, closed=True):
    Type: Literal["Task"]
    Resource: Expr[str]
    Comment: NotRequired[str]
    QueryLanguage: NotRequired[QueryLanguage]
    Next: NotRequired[str]
    End: NotRequired[Literal[True]]
    Parameters: NotRequired[Any]
    Arguments: NotRequired[Any]
    Credentials: NotRequired[Any]
    InputPath: NotRequired[str | None]
    OutputPath: NotRequired[str | None]
    ResultPath: NotRequired[str | None]
    ResultSelector: NotRequired[Any]
    Output: NotRequired[Any]
    Assign: NotRequired[Any]
    Retry: NotRequired[list[Retrier]]
    Catch: NotRequired[list[Catcher]]
    TimeoutSeconds: NotRequired[int]
    TimeoutSecondsPath: NotRequired[str]
    HeartbeatSeconds: NotRequired[int]
    HeartbeatSecondsPath: NotRequired[str]


class PassState(TypedDict, closed=True):
    Type: Literal["Pass"]
    Comment: NotRequired[str]
    QueryLanguage: NotRequired[QueryLanguage]
    Next: NotRequired[str]
    End: NotRequired[Literal[True]]
    Result: NotRequired[Any]
    Parameters: NotRequired[Any]
    InputPath: NotRequired[str | None]
    OutputPath: NotRequired[str | None]
    ResultPath: NotRequired[str | None]
    Output: NotRequired[Any]
    Assign: NotRequired[Any]


class WaitState(TypedDict, closed=True):
    Type: Literal["Wait"]
    Comment: NotRequired[str]
    QueryLanguage: NotRequired[QueryLanguage]
    Next: NotRequired[str]
    End: NotRequired[Literal[True]]
    Seconds: NotRequired[Any]
    Timestamp: NotRequired[str]
    SecondsPath: NotRequired[str]
    TimestampPath: NotRequired[str]
    InputPath: NotRequired[str | None]
    OutputPath: NotRequired[str | None]
    Output: NotRequired[Any]
    Assign: NotRequired[Any]


class ChoiceRule(TypedDict, total=False, extra_items=Any):
    """One rule of a `Choice`: a comparison (`Variable` plus one operator such as `StringEquals`), `And`/`Or`/`Not` of
    rules, or a JSONata `Condition`. Open, because there are about fifty comparison operators."""

    Variable: str
    Condition: Any
    Next: str
    And: list["ChoiceRule"]
    Or: list["ChoiceRule"]
    Not: "ChoiceRule"
    Assign: Any
    Output: Any


class ChoiceState(TypedDict, closed=True):
    Type: Literal["Choice"]
    Choices: list[ChoiceRule]
    Comment: NotRequired[str]
    QueryLanguage: NotRequired[QueryLanguage]
    Default: NotRequired[str]
    InputPath: NotRequired[str | None]
    OutputPath: NotRequired[str | None]
    Output: NotRequired[Any]
    Assign: NotRequired[Any]


class SucceedState(TypedDict, closed=True):
    Type: Literal["Succeed"]
    Comment: NotRequired[str]
    QueryLanguage: NotRequired[QueryLanguage]
    InputPath: NotRequired[str | None]
    OutputPath: NotRequired[str | None]
    Output: NotRequired[Any]


class FailState(TypedDict, closed=True):
    Type: Literal["Fail"]
    Comment: NotRequired[str]
    QueryLanguage: NotRequired[QueryLanguage]
    Error: NotRequired[str]
    ErrorPath: NotRequired[str]
    Cause: NotRequired[str]
    CausePath: NotRequired[str]


class Branch(TypedDict, closed=True):
    """A `Parallel` branch, or the item processor of a `Map`: a state graph of its own."""

    StartAt: str
    States: "Mapping[str, State]"
    Comment: NotRequired[str]
    ProcessorConfig: NotRequired[Any]


class ParallelState(TypedDict, closed=True):
    Type: Literal["Parallel"]
    Branches: list[Branch]
    Comment: NotRequired[str]
    QueryLanguage: NotRequired[QueryLanguage]
    Next: NotRequired[str]
    End: NotRequired[Literal[True]]
    Parameters: NotRequired[Any]
    Arguments: NotRequired[Any]
    InputPath: NotRequired[str | None]
    OutputPath: NotRequired[str | None]
    ResultPath: NotRequired[str | None]
    ResultSelector: NotRequired[Any]
    Output: NotRequired[Any]
    Assign: NotRequired[Any]
    Retry: NotRequired[list[Retrier]]
    Catch: NotRequired[list[Catcher]]


class MapState(TypedDict, closed=True):
    Type: Literal["Map"]
    ItemProcessor: NotRequired[Branch]
    Iterator: NotRequired[Branch]  # the older name of ItemProcessor
    Comment: NotRequired[str]
    QueryLanguage: NotRequired[QueryLanguage]
    Next: NotRequired[str]
    End: NotRequired[Literal[True]]
    ItemsPath: NotRequired[str]
    Items: NotRequired[Any]
    ItemSelector: NotRequired[Any]
    ItemReader: NotRequired[Any]
    ItemBatcher: NotRequired[Any]
    ResultWriter: NotRequired[Any]
    MaxConcurrency: NotRequired[int]
    MaxConcurrencyPath: NotRequired[str]
    ToleratedFailureCount: NotRequired[int]
    ToleratedFailurePercentage: NotRequired[float]
    Label: NotRequired[str]
    Parameters: NotRequired[Any]
    InputPath: NotRequired[str | None]
    OutputPath: NotRequired[str | None]
    ResultPath: NotRequired[str | None]
    ResultSelector: NotRequired[Any]
    Output: NotRequired[Any]
    Assign: NotRequired[Any]
    Retry: NotRequired[list[Retrier]]
    Catch: NotRequired[list[Catcher]]


type State = TaskState | PassState | WaitState | ChoiceState | SucceedState | FailState | ParallelState | MapState


class Definition(TypedDict, closed=True):
    """The `Definition` of an `AWS::StepFunctions::StateMachine`."""

    StartAt: str
    States: Mapping[str, State]
    Comment: NotRequired[str]
    QueryLanguage: NotRequired[QueryLanguage]
    TimeoutSeconds: NotRequired[int]
    Version: NotRequired[str]


def find_asl_problems(definition: Mapping[str, Any]) -> list[str]:
    """Every problem in the state machine `definition`, one readable line each, `[]` when the graph is sound. A path such as `States.Check` or `States.Map.Branches[0].Fetch` starts each line."""
    problems: list[str] = []
    try:
        size = len(json.dumps(definition).encode())
    except (TypeError, ValueError):
        size = 0
    if size > DEFINITION_BYTES:
        problems.append(f"the definition is {size} bytes, but Step Functions allows at most {DEFINITION_BYTES}")
    names: dict[str, str] = {}  # name -> where first seen
    _scope(definition, "States", problems, names, str(definition.get("QueryLanguage", "JSONPath")))
    return problems


def _scope(scope: Mapping[str, Any], where: str, problems: list[str], names: dict[str, str], language: str) -> None:
    states = scope.get("States")
    start = scope.get("StartAt")
    if not isinstance(states, Mapping) or not states:
        problems.append(f"{where}: no States")
        return
    if not isinstance(start, str):
        problems.append(f"{where}: no StartAt")
    elif start not in states:
        problems.append(f"{where}: StartAt names {start!r}, which is not a state here")

    successors: dict[str, list[str]] = {}
    terminal: set[str] = set()
    for name, state in states.items():
        at = f"{where}.{name}"
        if len(name) > STATE_NAME_CHARS:
            problems.append(f"{at}: the name is {len(name)} characters, but at most {STATE_NAME_CHARS} are allowed")
        if name in names:
            problems.append(f"{at}: the name is also used at {names[name]}; names must be unique in the whole machine")
        else:
            names[name] = at
        if not isinstance(state, Mapping):
            problems.append(f"{at}: a state must be an object")
            continue
        successors[name] = _state(state, at, name, states, problems, names, terminal, language)

    if not isinstance(start, str) or start not in states:
        return
    reached = {start}
    queue = deque([start])
    while queue:
        for target in successors.get(queue.popleft(), []):
            if target in states and target not in reached:
                reached.add(target)
                queue.append(target)
    for name in states:
        if name not in reached:
            problems.append(f"{where}.{name}: unreachable from StartAt")

    can_end = set(terminal)
    grew = True
    while grew:
        grew = False
        for name, targets in successors.items():
            if name not in can_end and any(t in can_end for t in targets):
                can_end.add(name)
                grew = True
    for name in states:
        if name in reached and name in successors and name not in can_end:
            problems.append(f"{where}.{name}: no path from here reaches an end (Succeed, Fail or End)")


def _state(
    state: Mapping[str, Any], at: str, name: str, states: Mapping[str, Any], problems: list[str],
    names: dict[str, str], terminal: set[str], language: str,
) -> list[str]:
    """Check one state; return the names it can go to and add `name` to `terminal` if it can end."""
    kind = state.get("Type")
    if kind not in STATE_TYPES:
        problems.append(f"{at}: Type is {kind!r}, expected one of {', '.join(sorted(STATE_TYPES))}")
        return []
    language = str(state.get("QueryLanguage", language))
    targets: list[str] = []

    def jump(field: str, target: Any) -> None:
        if not isinstance(target, str):
            if target is not None and not isinstance(target, Mapping):
                problems.append(f"{at}: {field} must be a state name")
            return
        if target not in states:
            problems.append(f"{at}: {field} names {target!r}, which is not a state in this scope")
        targets.append(target)

    has_next, has_end = "Next" in state, "End" in state
    if kind in ("Succeed", "Fail"):
        terminal.add(name)
        if has_next or has_end:
            problems.append(f"{at}: a {kind} state is already an end, so it has no Next or End")
    elif kind == "Choice":
        if has_next or has_end:
            problems.append(f"{at}: a Choice has no Next or End; its rules and Default say where to go")
        rules = state.get("Choices")
        if not isinstance(rules, Sequence) or isinstance(rules, str) or not rules:
            problems.append(f"{at}: Choices must be a non-empty list")
        else:
            for i, rule in enumerate(rules):
                if not isinstance(rule, Mapping):
                    problems.append(f"{at}.Choices[{i}]: a rule must be an object")
                    continue
                if "Next" not in rule:
                    problems.append(f"{at}.Choices[{i}]: no Next")
                else:
                    jump(f"Choices[{i}].Next", rule["Next"])
                _rule(rule, f"{at}.Choices[{i}]", language, problems)
        if "Default" in state:
            jump("Default", state["Default"])
    else:
        if has_next == has_end:
            problems.append(f"{at}: needs exactly one of Next and End" + (", has both" if has_next else ", has neither"))
        if has_next:
            jump("Next", state["Next"])
        if has_end:
            if state["End"] is not True:
                problems.append(f"{at}: End must be true")
            terminal.add(name)

    if kind in ("Task", "Parallel", "Map"):
        for i, catcher in enumerate(_listed(state, "Catch", at, problems)):
            _errors(catcher, f"{at}.Catch[{i}]", problems, last=i == len(state["Catch"]) - 1)
            if isinstance(catcher, Mapping):
                if "Next" not in catcher:
                    problems.append(f"{at}.Catch[{i}]: no Next")
                else:
                    jump(f"Catch[{i}].Next", catcher["Next"])
        for i, retrier in enumerate(_listed(state, "Retry", at, problems)):
            _errors(retrier, f"{at}.Retry[{i}]", problems, last=i == len(state["Retry"]) - 1)
            if isinstance(retrier, Mapping):
                _retry_numbers(retrier, f"{at}.Retry[{i}]", problems)
    else:
        for field in ("Retry", "Catch"):
            if field in state:
                problems.append(f"{at}: {field} is only for Task, Parallel and Map states, not {kind}")

    if kind == "Task" and "Resource" not in state:
        problems.append(f"{at}: a Task needs a Resource")
    if kind == "Wait":
        given = [f for f in _WAIT_FIELDS if f in state]
        if len(given) != 1:
            problems.append(f"{at}: a Wait needs exactly one of {', '.join(_WAIT_FIELDS)}, has {', '.join(given) or 'none'}")
    if kind == "Parallel":
        for i, branch in enumerate(_listed(state, "Branches", at, problems)):
            if isinstance(branch, Mapping):
                _scope(branch, f"{at}.Branches[{i}]", problems, names, language)
            else:
                problems.append(f"{at}.Branches[{i}]: a branch must be an object")
        if not state.get("Branches"):
            problems.append(f"{at}: a Parallel needs Branches")
    if kind == "Map":
        processor = state.get("ItemProcessor", state.get("Iterator"))
        if isinstance(processor, Mapping):
            _scope(processor, f"{at}.ItemProcessor", problems, names, language)
        else:
            problems.append(f"{at}: a Map needs an ItemProcessor")

    if language != "JSONata":
        for field in _PATH_FIELDS:
            if field in state:
                _path(state[field], f"{at}.{field}", problems, nullable=field in _NULLABLE_PATHS)
    return targets


def _listed(state: Mapping[str, Any], field: str, at: str, problems: list[str]) -> list[Any]:
    value = state.get(field, [])
    if isinstance(value, Sequence) and not isinstance(value, str):
        return list(value)
    problems.append(f"{at}: {field} must be a list")
    return []


def _errors(entry: Any, at: str, problems: list[str], *, last: bool) -> None:
    """`ErrorEquals` of a Retrier or Catcher."""
    if not isinstance(entry, Mapping):
        problems.append(f"{at}: must be an object")
        return
    errors = entry.get("ErrorEquals")
    if not isinstance(errors, Sequence) or isinstance(errors, str) or not errors:
        problems.append(f"{at}: ErrorEquals must be a non-empty list")
        return
    for error in errors:
        if isinstance(error, str) and error.startswith("States.") and error not in STATES_ERRORS:
            problems.append(f"{at}: {error!r} is not a Step Functions error name")
    if "States.ALL" in errors:
        if len(errors) > 1:
            problems.append(f"{at}: States.ALL must be the only entry of ErrorEquals")
        if not last:
            problems.append(f"{at}: States.ALL catches every error, so it must be in the last entry; the ones after it never run")


def _retry_numbers(retrier: Mapping[str, Any], at: str, problems: list[str]) -> None:
    bounds = {"IntervalSeconds": (1, None), "MaxAttempts": (0, 99_999_999), "BackoffRate": (1.0, None), "MaxDelaySeconds": (1, 31_622_401)}
    for field, (low, high) in bounds.items():
        value = retrier.get(field)
        if value is None or isinstance(value, Mapping):
            continue
        if isinstance(value, bool) or not isinstance(value, int | float):
            problems.append(f"{at}: {field} must be a number, not {value!r}")
        elif value < low or (high is not None and value > high):
            problems.append(f"{at}: {field} is {value}, but must be {low}" + (f" to {high}" if high is not None else " or more"))


def _rule(rule: Mapping[str, Any], at: str, language: str, problems: list[str]) -> None:
    """A Choice rule: its `Variable`, and the rules nested in `And`, `Or` and `Not`."""
    if language != "JSONata" and "Variable" in rule:
        _path(rule["Variable"], f"{at}.Variable", problems, nullable=False)
    for combinator in ("And", "Or"):
        inner = rule.get(combinator)
        if isinstance(inner, Sequence) and not isinstance(inner, str):
            for i, sub in enumerate(inner):
                if isinstance(sub, Mapping):
                    _rule(sub, f"{at}.{combinator}[{i}]", language, problems)
    if isinstance(rule.get("Not"), Mapping):
        _rule(rule["Not"], f"{at}.Not", language, problems)


def _path(value: Any, at: str, problems: list[str], *, nullable: bool) -> None:
    if isinstance(value, Mapping) or (value is None and nullable):
        return  # an intrinsic, or an explicit null
    if not isinstance(value, str) or not value.startswith("$"):
        problems.append(f"{at}: {value!r} is not a path; it must start with '$'")


def find_state_machine_problems(template: Mapping[str, Any]) -> list[str]:
    """`find_asl_problems` for every `AWS::StepFunctions::StateMachine` in `template` whose `Definition` is a literal object, or whose `DefinitionString` is a literal JSON string. A definition built with an intrinsic cannot be read, and is left out."""
    problems: list[str] = []
    for logical, resource in template.get("Resources", {}).items():
        if not isinstance(resource, Mapping) or resource.get("Type") != "AWS::StepFunctions::StateMachine":
            continue
        props = resource.get("Properties", {})
        definition = props.get("Definition")
        text = props.get("DefinitionString")
        if isinstance(text, Mapping) and isinstance(text.get("Fn::Sub"), str):
            text = text["Fn::Sub"]  # `${Name}` placeholders sit inside strings, so the JSON still parses
        if definition is None and isinstance(text, str):
            try:
                definition = json.loads(text)
            except ValueError as error:
                problems.append(f"{logical}: DefinitionString is not valid JSON ({error})")
                continue
        if isinstance(definition, Mapping):
            problems += [f"{logical}.{p}" for p in find_asl_problems(definition)]
    return problems
