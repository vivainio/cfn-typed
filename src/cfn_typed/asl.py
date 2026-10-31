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

Reuse in a big machine is `Fragment`: a piece of graph with named open exits that you wire up, rename and edit in bulk,
then `build()` into a `Definition` that is checked. `find_machine_differences` compares two definitions, which is the
test that a refactor changed nothing, and `to_mermaid` draws one for review. Conventions such as a polling loop are
yours to write on top; a fragment-returning function is all they need.

Intrinsics (`Fn::Sub` and the like) are skipped wherever a plain value is expected, so the check also works on a
definition inside a template. `cfn_typed.checks.find_all_problems` runs it on every `Definition` it finds.
"""

import copy
import json
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Literal, NotRequired, cast

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


# --- fragments ----------------------------------------------------------------------------------------------------


class Exit(str):
    """A placeholder for a transition that is not wired yet: put `Exit("done")` where a state name goes (`Next`, `Default`, `Choices[].Next`, `Catch[].Next`). It is a `str`, so the types accept it. A state that needs a `Next` and has none gets `Exit("next")`."""


type _Site = tuple[str, tuple[str | int, ...]]  # a state name, and the key path of the transition inside it
_NEEDS_NEXT = frozenset({"Task", "Pass", "Wait", "Parallel", "Map"})


def _sites(states: Mapping[str, Any]) -> list[tuple[Exit, _Site]]:
    """Every `Exit` in the transitions of `states` (this scope only; nested scopes are closed)."""
    found: list[tuple[Exit, _Site]] = []

    for name, state in states.items():
        if isinstance(state.get("Next"), Exit):
            found.append((state["Next"], (name, ("Next",))))
        if isinstance(state.get("Default"), Exit):
            found.append((state["Default"], (name, ("Default",))))
        for field in ("Choices", "Catch"):
            for i, entry in enumerate(state.get(field, [])):
                if isinstance(entry.get("Next"), Exit):
                    found.append((entry["Next"], (name, (field, i, "Next"))))
    return found


def _set(state: dict[str, Any], path: tuple[str | int, ...], value: Any) -> None:
    holder: Any = state
    for key in path[:-1]:
        holder = holder[key]
    holder[path[-1]] = value


class Fragment:
    """A piece of a state graph: its states, the one it starts at, and the transitions not wired yet (its *exits*, each named, see `Exit`).

        poll = Fragment("Wait", {"Wait": {...,"Next": "Run"}, "Run": {..., "Next": "Check"}, "Check": {"Type": "Choice", ...,
                        "Choices": [{..., "Next": Exit("done")}], "Default": Exit("again")}})
        machine = chain(prepare, poll.wire("again", "Wait").prefixed("Tenant"), finish).build()

    A fragment never changes: every method returns a new one. Exits of the same name are all wired together, so two
    fragments that each leave through `Exit("failed")` share one failure handler. `build()` refuses a fragment that still
    has exits, and one whose graph `find_asl_problems` rejects.
    """

    __slots__ = ("start", "states")

    def __init__(self, start: str, states: Mapping[str, Mapping[str, Any]]) -> None:
        self.start = start
        self.states: dict[str, dict[str, Any]] = copy.deepcopy({k: dict(v) for k, v in states.items()})
        for state in self.states.values():
            if state.get("Type") in _NEEDS_NEXT and "Next" not in state and "End" not in state:
                state["Next"] = Exit("next")

    @property
    def exits(self) -> frozenset[str]:
        """The names of the transitions not wired yet."""
        return frozenset(str(e) for e, _ in _sites(self.states))

    def __repr__(self) -> str:
        return f"Fragment(start={self.start!r}, states={list(self.states)}, exits={sorted(self.exits)})"

    def _merged(self, other: "Fragment") -> dict[str, dict[str, Any]]:
        clash = sorted(set(self.states) & set(other.states))
        if clash:
            raise ValueError(f"both fragments have states named {', '.join(map(repr, clash))}; use prefixed() on one of them")
        return {**self.states, **other.states}

    def wire(self, exit: str, target: "str | Fragment") -> "Fragment":
        """Point every exit called `exit` at `target`: the name of a state (in the machine this ends up in), or a fragment, whose states are added and whose start is the target."""
        sites = [site for e, site in _sites(self.states) if e == exit]
        if not sites:
            raise ValueError(f"no exit {exit!r}; the exits are {sorted(self.exits) or 'none'}")
        states = self._merged(target) if isinstance(target, Fragment) else self.states
        name = target.start if isinstance(target, Fragment) else target
        result = Fragment(self.start, states)
        for state_name, path in sites:
            _set(result.states[state_name], path, name)
        return result

    def then(self, other: "Fragment") -> "Fragment":
        """`wire("next", other)`: continue with `other` where this fragment's plain `Next` was left open."""
        return self.wire("next", other)

    def end(self, exit: str = "next") -> "Fragment":
        """Finish the machine at every exit called `exit`, with `End: true`. Only a plain `Next` can become an end; a `Choice` rule or a `Catch` cannot, so wire those to a `Succeed` or `Fail` state."""
        sites = [site for e, site in _sites(self.states) if e == exit]
        if not sites:
            raise ValueError(f"no exit {exit!r}; the exits are {sorted(self.exits) or 'none'}")
        result = Fragment(self.start, self.states)
        for state_name, path in sites:
            if path != ("Next",) or result.states[state_name].get("Type") == "Choice":
                raise ValueError(f"{state_name}: {'.'.join(map(str, path))} cannot be an End; wire it to a Succeed or Fail state")
            del result.states[state_name]["Next"]
            result.states[state_name]["End"] = True
        return result

    def include(self, other: "Fragment") -> "Fragment":
        """Add `other`'s states without connecting them to anything: shared handlers that other states name, or branches a `Choice` reaches by name. `other`'s exits become this fragment's exits."""
        return Fragment(self.start, self._merged(other))

    def prefixed(self, prefix: str) -> "Fragment":
        """The same fragment with every state name (and `StartAt`, in nested scopes too) starting with `prefix`, and the transitions between them following. A transition to a name that is not in the fragment, or an `Exit`, is left alone. This is how one pattern is used twice: state names are unique across a whole machine."""
        states, start = _rename(self.start, self.states, lambda name: prefix + name)
        return Fragment(start, states)

    def map_states(self, fn: Callable[[dict[str, Any]], Mapping[str, Any]], *, where: str | Callable[[Mapping[str, Any]], bool] | None = None) -> "Fragment":
        """Replace each state with `fn(state)` (`fn` gets its own copy, and returns the state to use). `where` limits it to a `Type` such as `"Task"`, or to the states a predicate accepts. Only this scope: a state inside a `Parallel` branch or a `Map` is not visited. This is how a shared `Catch` or retry policy is applied to a whole fragment."""
        def chosen(state: Mapping[str, Any]) -> bool:
            return where is None or (state.get("Type") == where if isinstance(where, str) else where(state))

        return Fragment(self.start, {n: (fn(copy.deepcopy(s)) if chosen(s) else s) for n, s in self.states.items()})

    def build(self, **top: Any) -> Definition:
        """The finished `Definition`. `top` adds the top-level keys, such as `Comment` or `QueryLanguage`. Raises `ValueError` listing the open exits, or the problems `find_asl_problems` finds."""
        if self.exits:
            raise ValueError(f"unwired exits: {', '.join(sorted(self.exits))}")
        definition = cast(Definition, {**top, "StartAt": self.start, "States": copy.deepcopy(self.states)})
        problems = find_asl_problems(definition)
        if problems:
            raise ValueError("the state machine is not sound:\n" + "\n".join(f"  {p}" for p in problems))
        return definition


def step(name: str, state: State | Mapping[str, Any]) -> Fragment:
    """A fragment of one state, named `name`."""
    return Fragment(name, {name: state})


def chain(*fragments: Fragment) -> Fragment:
    """The fragments one after another: each one's `Exit("next")` leads to the next one's start. The exits that remain are the last one's, and any other exits left open along the way."""
    if not fragments:
        raise ValueError("chain() needs at least one fragment")
    result = fragments[0]
    for nxt in fragments[1:]:
        result = result.then(nxt)
    return result


def _rename(start: str, states: Mapping[str, Mapping[str, Any]], fn: Callable[[str], str]) -> tuple[dict[str, dict[str, Any]], str]:
    mapping = {name: fn(name) for name in states}

    def target(value: Any) -> Any:
        return mapping.get(value, value) if isinstance(value, str) and not isinstance(value, Exit) else value

    out: dict[str, dict[str, Any]] = {}
    for name, original in states.items():
        state = copy.deepcopy(dict(original))
        for key in ("Next", "Default"):
            if key in state:
                state[key] = target(state[key])
        for field in ("Choices", "Catch"):
            for entry in state.get(field, []):
                if "Next" in entry:
                    entry["Next"] = target(entry["Next"])
        for branch in state.get("Branches", []):
            branch["States"], branch["StartAt"] = _rename(branch["StartAt"], branch["States"], fn)
        for key in ("ItemProcessor", "Iterator"):
            if isinstance(state.get(key), dict):
                state[key]["States"], state[key]["StartAt"] = _rename(state[key]["StartAt"], state[key]["States"], fn)
        out[mapping[name]] = state
    return out, mapping.get(start, start)


# --- comparing and drawing ----------------------------------------------------------------------------------------


def find_machine_differences(built: Any, expected: Any) -> list[str]:
    """Where the two definitions differ, one readable line each, `[]` when they are the same machine. Key order does not matter; the order of a list does (`Choices` and `Retry` are evaluated in order). This is the test that a refactor into fragments changed nothing."""
    out: list[str] = []
    _diff(built, expected, "", out)
    return out


def _diff(built: Any, expected: Any, path: str, out: list[str]) -> None:
    where = path or "(definition)"
    if isinstance(built, Mapping) and isinstance(expected, Mapping):
        for key in expected:
            if key not in built:
                out.append(f"{path}.{key}: missing, expected {_short(expected[key])}".lstrip("."))
        for key in built:
            if key not in expected:
                out.append(f"{path}.{key}: not expected, got {_short(built[key])}".lstrip("."))
        for key in built.keys() & expected.keys():
            _diff(built[key], expected[key], f"{path}.{key}".lstrip("."), out)
    elif isinstance(built, list) and isinstance(expected, list):
        if len(built) != len(expected):
            out.append(f"{where}: {len(built)} items, expected {len(expected)}")
        for i, (b, e) in enumerate(zip(built, expected)):
            _diff(b, e, f"{path}[{i}]", out)
    elif built != expected or type(built) is not type(expected) and not {type(built), type(expected)} <= {int, float}:
        out.append(f"{where}: {_short(built)}, expected {_short(expected)}")


def _short(value: Any) -> str:
    text = json.dumps(value, default=str)
    return text if len(text) <= 60 else text[:57] + "..."


def to_mermaid(definition: Mapping[str, Any]) -> str:
    """Mermaid `stateDiagram-v2` source for `definition`: `Choice` states as diamonds, `Catch` edges labelled `catch`, a `Parallel` or `Map` as a box around its inner graph. Paste it into any Mermaid renderer to review a big machine."""
    lines = ["stateDiagram-v2"]
    ids: dict[str, str] = {}

    def ident(name: str) -> str:
        return ids.setdefault(name, f"s{len(ids)}")

    def label(text: Any) -> str:
        return str(text).replace(":", " ").replace('"', "'").replace("\n", " ")

    def scope(sc: Mapping[str, Any], indent: str) -> None:
        states = sc.get("States", {})
        lines.append(f"{indent}[*] --> {ident(sc['StartAt'])}") if sc.get("StartAt") in states else None
        for name, st in states.items():
            sid, kind = ident(name), st.get("Type")
            if kind == "Choice":
                lines.append(f'{indent}state "{label(name)}" as {sid} <<choice>>')
            elif kind in ("Parallel", "Map"):
                lines.append(f'{indent}state "{label(name)}" as {sid} {{')
                inner = [st["ItemProcessor"] if "ItemProcessor" in st else st.get("Iterator")] if kind == "Map" else st.get("Branches", [])
                for i, branch in enumerate(b for b in inner if isinstance(b, Mapping)):
                    if i:
                        lines.append(f"{indent}    --")
                    scope(branch, indent + "    ")
                lines.append(f"{indent}}}")
            else:
                lines.append(f'{indent}state "{label(name)}" as {sid}')
        for name, st in states.items():
            sid = ident(name)
            if isinstance(st.get("Next"), str):
                lines.append(f"{indent}{sid} --> {ident(st['Next'])}")
            if st.get("End") is True or st.get("Type") in ("Succeed", "Fail"):
                lines.append(f"{indent}{sid} --> [*]")
            for rule in st.get("Choices", []):
                if isinstance(rule.get("Next"), str):
                    lines.append(f"{indent}{sid} --> {ident(rule['Next'])}: {label(rule.get('Variable', 'if'))}")
            if isinstance(st.get("Default"), str):
                lines.append(f"{indent}{sid} --> {ident(st['Default'])}: default")
            for catcher in st.get("Catch", []):
                if isinstance(catcher.get("Next"), str):
                    lines.append(f"{indent}{sid} --> {ident(catcher['Next'])}: catch")

    scope(definition, "    ")
    return "\n".join(lines) + "\n"
