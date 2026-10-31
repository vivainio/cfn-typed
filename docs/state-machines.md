# State machines

`cfn_typed.asl` is for Step Functions state machines: the Amazon States Language as typed Python, a check of the
state graph, and a few pieces for reuse in a machine too big to write out twice. Like the rest of the
[core](core.md) it is mechanics, not opinion. It knows what the ASL spec says; it does not know what a polling loop
or a retry policy should look like in your workflow. Those are ordinary Python functions you write on top of it.

```python
from cfn_typed.asl import Definition, Exit, Fragment, chain, step, find_asl_problems, to_mermaid
```

A state machine is a `Definition` (a plain dict) in the `Definition` property of an
`AWS::StepFunctions::StateMachine`. Nothing here changes how it renders.

## Typed states

`Definition`, `TaskState`, `PassState`, `WaitState`, `ChoiceState`, `SucceedState`, `FailState`, `ParallelState`,
`MapState`, `Retrier`, `Catcher` and `Branch` are closed `TypedDict`s, so the type checker rejects a misspelled key, a
state without its `Type`, a `Task` without a `Resource`, and a `Choice` or `Succeed` with a `Next`:

```python
machine: Definition = {
    "StartAt": "Fetch",
    "States": {
        "Fetch": {"Type": "Task", "Resource": fetch_arn, "Next": "Done"},
        "Done": {"Type": "Succeed"},
    },
}
```

`ChoiceRule` accepts any comparison operator (`StringEquals`, `IsTimestamp`, ... about fifty of them), and its other
keys are checked. `Resource` is an `Expr[str]`, so an intrinsic is fine. Fields that hold arbitrary JSON
(`Parameters`, `ResultSelector`, `Assign`, ...) are `Any`.

## Check the graph

`find_asl_problems(definition)` returns one readable line per problem, `[]` when the graph is sound. These are things
Step Functions reports at deploy time, or not until the machine runs:

| Check | Reported when |
|---|---|
| transitions | `StartAt`, `Next`, `Default`, `Choices[].Next` or `Catch[].Next` names a state that is not in the same scope |
| scopes | a transition crosses into or out of a `Parallel` branch or a `Map` item processor, each of which is its own graph |
| names | a state name is used twice anywhere in the machine (nested scopes included), or is over 80 characters |
| `Next` and `End` | a state has both or neither; a `Choice`, `Succeed` or `Fail` has either |
| reachability | a state cannot be reached from `StartAt`, or a reachable state has no path to an end (a loop with no exit) |
| `Retry`, `Catch` | `ErrorEquals` is empty, names a `States.` error that does not exist, has `States.ALL` with other entries, or `States.ALL` is not in the last entry (the entries after it never run); `IntervalSeconds`, `MaxAttempts`, `BackoffRate` or `MaxDelaySeconds` is out of range; either is on a state type that cannot have it |
| `Wait` | not exactly one of `Seconds`, `Timestamp`, `SecondsPath`, `TimestampPath` |
| other required keys | a `Task` without `Resource`, a `Parallel` without `Branches`, a `Map` without an `ItemProcessor`, an unknown `Type` |
| paths | `InputPath`, `OutputPath`, `ResultPath`, `ItemsPath`, `SecondsPath`, ... or a `Choice` `Variable` that does not start with `$` (`null` is allowed where ASL allows it; not checked under `QueryLanguage: JSONata`) |
| size | the definition is over 1,048,576 bytes |

Each line starts with where the problem is: `States.Check: Default names 'Nowhere', which is not a state in this
scope`, or `States.Fan.Branches[0].Inner: ...` inside a branch. Not checked: the contents of `Parameters` and
`Output`, JSONPath beyond the leading `$`, JSONata expressions, and whether a `Resource` exists.

### In a template

`find_state_machine_problems(template)` runs the same check on every `AWS::StepFunctions::StateMachine` in a template,
with the logical ID in front of each line. It reads a `Definition` object, or a literal `DefinitionString`: a plain JSON
string, or `Fn::Sub` of one with no variables map. A definition assembled with `Fn::Join` or other intrinsics cannot be
read and is skipped. [`find_all_problems`](patterns/company-rules.md) and `assert_template_ok` run it as the `asl` check,
so `cfn-typed check` and the golden-file tests cover it without further work.

In a test:

```python
from cfn_typed.testing import assert_state_machine_valid, assert_state_machines_valid

def test_machine() -> None:
    assert_state_machine_valid(build_machine())            # one definition
    assert_state_machines_valid(build("prod"))             # every machine in a template
```

Both fail with every problem listed, one per line.

## Starting from an existing machine

`cfn-typed import --asl template.json -o stack.py` writes each state machine's `DefinitionString` as a `Definition`
object instead of a 100 KB string. See [`import`](cli.md#import-start-from-an-existing-template). The same is
`importer.structure_state_machines(template)` in code. With `Fn::Sub`, each string that contains `${` becomes its own
`Fn::Sub`, so the substitutions still happen. The result is a different template property than the original
(`Definition`, not `DefinitionString`), so the exact round trip that `import` otherwise keeps does not hold for it.
Check a deploy before relying on it.

## Fragments: reuse in a big machine

The part of a big machine that hurts is repetition: the same wait, run and check loop for ten operations, the same
`Catch` on sixty Tasks. A `Fragment` is a piece of graph that knows which of its transitions are not wired yet, so the
piece can be written once, renamed, wired differently each time, and edited in bulk.

### Exits

Put `Exit("name")` where a state name goes. It is a `str` subclass, so the typed states accept it in `Next`,
`Default`, `Choices[].Next` and `Catch[].Next`. A Task, Pass, Wait, Parallel or Map with no `Next` and no `End` gets
`Exit("next")` for free, so a plain sequence needs no markers at all.

```python
from cfn_typed.asl import Exit, Fragment

poll = Fragment("Wait", {
    "Wait": {"Type": "Wait", "SecondsPath": "$.delay", "Next": "Run"},
    "Run": {
        "Type": "Task", "Resource": run_arn, "Next": "Check",
        "Catch": [{"ErrorEquals": ["States.ALL"], "Next": Exit("failed")}],
    },
    "Check": {
        "Type": "Choice",
        "Choices": [{"Variable": "$.ok", "BooleanEquals": True, "Next": Exit("done")}],
        "Default": "Wait",                      # a loop back inside the fragment is just a name
    },
})
poll.exits      # frozenset({"done", "failed"})
```

`Fragment(start, states)` copies what it is given. A fragment never changes: every method below returns a new one.

### Wiring

| Call | What it does |
|---|---|
| `step(name, state)` | a fragment of one state |
| `frag.wire("done", target)` | point every exit called `done` at `target`: a state name, or another fragment (its states are added, its start is the target) |
| `frag.then(other)` | `wire("next", other)` |
| `chain(a, b, c)` | `a.then(b).then(c)` |
| `frag.end("next")` | finish at every exit of that name with `End: true`; only a plain `Next` can end (wire a `Choice` rule or a `Catch` to a `Succeed` or `Fail` state instead) |
| `frag.include(other)` | add `other`'s states without connecting them: a shared failure handler that other states name, or branches a `Choice` reaches by name; its exits become this fragment's |

Exits of the same name are wired together. Two fragments that both leave through `Exit("failed")` share one
failure handler once you wire `failed`, and a typo in an exit name is an error (`no exit 'faild'; the exits are
['done', 'failed']`), not a silent no-op. Joining two fragments that have a state of the same name is an error that
tells you to use `prefixed`.

```python
machine = (
    chain(step("Prepare", {"Type": "Task", "Resource": prepare_arn}), poll)
    .wire("done", step("Done", {"Type": "Succeed"}))
    .wire("failed", step("Failed", {"Type": "Fail", "Error": "RunFailed"}))
    .build(Comment="Prepare, then poll until ok")
)
```

### Using a pattern twice

State names are unique across a whole machine, so a second copy of `poll` needs different names.
`frag.prefixed("Tenant_")` renames every state and `StartAt`, including inside `Parallel` branches and `Map` item
processors, and rewrites the transitions between them to match. A transition to a name that is not in the fragment (a
shared `Common_Failed`, say) and every `Exit` is left alone.

```python
two = (
    poll.prefixed("A_").wire("done", poll.prefixed("B_"))     # A_Wait .. A_Check, then B_Wait .. B_Check
    .wire("done", step("Done", {"Type": "Succeed"}))
    .wire("failed", step("Failed", {"Type": "Fail"}))
    .build()
)
```

### Editing every state at once

`frag.map_states(fn, where="Task")` replaces each matching state with `fn(state)`. `fn` receives its own copy and
returns the state to use; `where` is a `Type` name, or a predicate that takes the state, or omitted for every state. Only
the fragment's own scope is visited: a Task inside a `Parallel` branch or a `Map` is not. Use it for a shared policy:

```python
def with_failure_handler(state):
    return {**state, "Catch": [{"ErrorEquals": ["States.ALL"], "Next": "Common_Failed", "ResultPath": "$.error"}]}

guarded = poll.map_states(with_failure_handler, where="Task")
```

This is better than a `task()` factory that every call site has to remember to use, because it also reaches states you
did not write, such as a fragment from another module.

### Building

`frag.build(**top)` returns the `Definition`; `top` adds top-level keys such as `Comment`, `QueryLanguage` or
`TimeoutSeconds`. It raises `ValueError` if any exit is still open (`unwired exits: done, failed`) or if
`find_asl_problems` finds anything, listing every problem. A forgotten exit or a dangling transition therefore fails
where the machine is built, not at deploy.

### Writing your own patterns

There is deliberately no built-in `poll_loop`. What a polling loop looks like depends on the fields your task
returns (`$.finished`, `$.wait_time`, ...) and on how you want failures routed, and that is your service's contract.
A pattern is a function that returns a `Fragment`, with the exits as its interface:

```python
def poll_loop(op: str, run_arn: str) -> Fragment:
    """Wait, run, check. Exits: `done`, `failed`."""
    return Fragment(f"Wait_{op}", {...}).prefixed("")      # whatever shape you need
```

Keep the names the pattern chooses inside it, give it a prefix argument or call `prefixed` at the call site, and let
callers decide where `done` and `failed` go.

## Proving a refactor changed nothing

Rewriting a 140-state machine as fragments is only safe if the result is the same machine. Keep the original definition
(a JSON file, or the output of `import --asl`) and compare:

```python
from cfn_typed.testing import assert_same_machine

def test_machine_is_unchanged() -> None:
    assert_same_machine(build_machine(), json.loads(Path("sm_original.json").read_text()))
```

`find_machine_differences(built, expected)` returns the differences, one per line, and `assert_same_machine` fails
with them:

```text
States.Fetch.Retry[0].MaxAttempts: 3, expected 9
States.Extra: missing, expected {"Type": "Succeed"}
States.Check.Choices: 1 items, expected 2
```

Key order is ignored. The order of a list is not, because `Choices` and `Retry` are evaluated in order. `1` and
`true` differ; `1` and `1.0` do not. Differences are reported against the first argument.

## Drawing a machine

`to_mermaid(definition)` returns [Mermaid](https://mermaid.js.org) `stateDiagram-v2` source: `Choice` states are
diamonds, `Catch` edges are labelled `catch`, and a `Parallel` or `Map` is a box around its inner graph (branches
separated by a dashed line). Write it to a file and paste it into a Mermaid renderer to review a machine of
hundreds of states, or commit it next to the definition so a change to the graph shows in the pull request.

```python
Path("machine.mmd").write_text(to_mermaid(machine))
```

## Where this stops

Not built, on purpose: a library of ready-made loops and retry sets (they encode one workflow's field names and error
classes), a builder that hides state names behind objects, deriving the state machine's IAM role from its Tasks, and
splitting a machine into child executions. See [Patterns](patterns/index.md) for how the rest of the book treats
opinions.
