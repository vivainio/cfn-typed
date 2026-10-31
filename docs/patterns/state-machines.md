# Working with state machines

A Step Functions machine that grew for years is usually one 3,000-line JSON string with the same eight states pasted
sixty times. This page is a walk through porting one to Python with [`cfn_typed.asl`](../state-machines.md): how to
look at it first, how to port it without changing it, how to prove that, and what to fix afterwards. It is written from
a real port of a 143-state machine, but the machine used here is made up: 23 states, three operations, with the same
kinds of quirks. Everything is in `examples/state_machine/` and is run by the test suite, so the code on this page
works.

!!! note "A pattern is an opinion"
    The helpers below (`task`, `status_loop`, ...) belong to this made-up machine. Yours will look different, because
    what a polling loop returns and where errors go is your service's contract. What carries over is the method.

## The machine

`original.json` is a "ledger runner": a `Route` choice on `$.action` sends the run to one of three operations.

- **ImportInvoices**: start a task, poll its status until `$.finished`, finish. Its failure handler has no retry and no
  catch.
- **ReconcileLedger**: an optional timed start, a task, a `Map` over the accounts, a polling loop on `$.continue`, finish.
- **ArchiveReports**: a task, a `Parallel` of two branches, a notification.

Each operation ends in a shared `Common_Succeeded` or `Common_Failed`, and has its own `Perform_...Failed` handler.

## Step 0: get the definition as JSON

From a template, `cfn-typed import --asl template.json` writes the definition as a Python object (see
[`import`](../cli.md#import-start-from-an-existing-template)). From a deployed machine,
`aws stepfunctions describe-state-machine --state-machine-arn ARN --query definition --output text`. Either way, keep
the JSON file: it is the original you will compare against until the end.

!!! warning "Scrub before you commit"
    A real definition holds account IDs, Lambda ARNs, bucket names, internal hostnames and sometimes literal secrets in
    `Parameters`. Keep the real file out of the repository (or out of the tracked directory). For anything you commit,
    including test fixtures and the examples you share with colleagues, replace every account-specific value with a
    `${...}` placeholder or an invented name, as `examples/state_machine/original.json` does. A fixture made up from
    scratch is better than a scrubbed copy: nothing is left to miss.

## Step 1: survey before you write anything

Count what repeats. `survey.py` prints the numbers that decide which helpers are worth writing:

```python
--8<-- "examples/state_machine/survey.py:survey"
```

On the made-up machine:

```text
23 states: {'Choice': 4, 'Task': 12, 'Wait': 3, 'Map': 1, 'Parallel': 1, 'Succeed': 1, 'Fail': 1}
12 tasks, 7 distinct bodies (ignoring Next): the fewer, the more a helper will save
where errors go: Perform_ImportFailed x4, Perform_ReconcileFailed x3, Common_Failed x3, Perform_ArchiveFailed x3
polling loops (a Wait that leads to a Task): Wait_ImportStatus, Wait_StartReconcile, Wait_ReconcileStaus
tasks with no Catch (handlers, or forgotten?): Perform_ImportFailed
```

Read it for three things. **Few distinct task bodies** means a `task()` helper will pay off; in the real machine, 71 Tasks
had 17 distinct bodies. **Where errors go** shows the operation boundaries: each family of states that catches into the
same handler is one operation, and a state that catches somewhere else is either a deliberate choice or a mistake.
**Polling loops** are your first pattern. (`Wait_StartReconcile` is a timed start, not a loop; the survey is a rough
tool.)

## Step 2: port it without changing it

The rule for the first pass: **keep every state name, and reproduce every quirk.** The goal is a Python machine that
`assert_same_machine` says is the original. Improving it is Step 3, and doing both at once is how a port ends up
unverifiable.

Start with the things that are the same everywhere:

```python
--8<-- "examples/state_machine/port.py:policies"
```

Then the builders. `Exit("succeeded")`, `Exit("error")` and `Exit("failed")` are the three ways out of an operation:
the shared success state, the shared failure state, and the operation's own failure handler. A task that should catch
into its operation's handler says `catch_to=FAILED`; the operation wires `failed` to the right handler once, instead of
repeating its name on every task.

```python
--8<-- "examples/state_machine/port.py:builders"
```

Each operation is a function that returns a `Fragment`. Its states are written with the builders, and the name of
each state is the original's:

```python
--8<-- "examples/state_machine/port.py:operations"
```

Look at what the port made you write down. `Fetch_Accounts` catches into the *import* handler, which is almost
certainly a copy-paste slip, and the port gave it its own exit name (`import_failed`) so that the oddity is visible in
the code. `Wait_ReconcileStaus` has a typo. `Check_ReconcileStatus` catches into
`Common_Failed` where its neighbours catch into the handler. None of this was visible in the JSON.

Finally the router, and the assembly:

```python
--8<-- "examples/state_machine/port.py:build"
```

The test is the gate. It fails with every difference listed, which is how you find your own mistakes (the first
version of this example had `$.finished` where the reconcile loop uses `$.continue`):

```python
from cfn_typed.testing import assert_same_machine

def test_port_is_the_original() -> None:
    assert_same_machine(build(), json.loads(Path("original.json").read_text()))
```

## Hints for porters

**Method**

- **Port verbatim first, then change.** Two commits, or at least two steps: one that must produce no difference, and
  one whose every difference you can name.
- **Port one operation at a time.** `find_machine_differences` compares whole machines, but you can compare a subset:
  after wiring the shared exits, `fragment.states == {name: original["States"][name] for name in fragment.states}`.
  The operation is done when that holds.
- **`build()` is a second test.** It refuses open exits (`unwired exits: failed`) and an unsound graph, and it names the
  state. Run it early and let it guide you to the exit you forgot to wire.
- **Group by where errors go.** The `Catch` target is the best clue to an operation's boundary, better than the name
  prefix. Names are the least reliable thing in an old machine.
- **Write the survey down in a comment.** "17 distinct bodies, 3 retry sets, 10 handlers" tells the next person what the
  helpers are for.

**What to expect in an old machine**

- **Inconsistencies are the norm.** Expect one task per operation that catches somewhere else, handlers that differ
  from each other, names that nearly match (`Upscale_` next to `UpScale_`, `Prestep` next to `PreStep`), and a loop
  that checks `$.finished` where all its siblings check `$.continue`. Keep them in the port, name them in a comment,
  decide in Step 3.
- **A `Choice` `Default` is not the `Catch`.** The same state family often sends a failed *check* to the shared failure
  state and an *error* to the operation's handler. They are separate exits; do not merge them to tidy up.
- **Order matters in lists.** `Choices` are evaluated first-match, `Retry` and `Catch` too. `assert_same_machine` compares
  lists in order on purpose. Key order does not matter.
- **Integers stay integers.** `BackoffRate: 2` and `2.0` compare equal in Python and render differently. `retry()`
  defaults to the int, and a diff of the rendered template stays quiet.
- **A loop is not always a loop.** `Wait` then `Task` is a poll only if a `Choice` sends control back. A timed start
  (`TimestampPath`) looks similar and is not. Check the choice before generalising.
- **Some states are one-offs.** Not everything is a pattern. A state that appears once is written out as a literal dict
  in its operation, and that is fine; resist a helper with a parameter for each exception. If a helper needs more than
  three or four flags to cover the cases, make two helpers or leave the odd cases literal.

**Names**

- **State names are not free to change.** They appear in execution history, CloudWatch Logs and metrics, X-Ray
  traces, alarms keyed on a state, and often in the worker Lambda (`$$.State.Name`, or branching on a name it was
  given). Before any rename, search every consumer you have: dashboards, alarms, the Lambda source, runbooks.
- **A rename is a change, not a refactor.** Prove it separately (Step 3), deploy it separately, and leave a note about
  executions that are in flight: a running execution keeps the definition it started with.
- **Fix typos last.** A typo you kept costs nothing. A fixed one has to be right everywhere at once.

**Getting it into a template**

- **Placeholders.** Strings with `${AWS::Region}`, `${AWS::AccountId}` or `${Stage}` must become `Fn::Sub`.
  `cfn_typed.asl.substituted(definition)` wraps each such string. The alternative is `DefinitionSubstitutions`, which Step
  Functions fills in itself. Deploy to a throwaway stack and look at the deployed definition (`describe-state-machine`)
  before trusting either.
- **`Definition`, not `DefinitionString`.** CloudFormation sees a different property, so the first deploy shows a change
  to it even when the machine is identical. The deployed definition should be the same; compare it with the original
  after the first deploy.
- **Size.** The definition limit is 1 MB, but a machine of hundreds of states more often hits other limits first: 25,000
  events of execution history, 256 KB of state payload. If an operation is already a self-contained fragment with its
  own exits, it can be moved into a child machine later without touching the others.

## Step 3: fix what the port showed

Now change things, and make every change a line you can review. The first step is to prove that the tidy-up is the
*only* change: take the original, apply the same renames to it, and compare.

```python
--8<-- "examples/state_machine/tidy.py:tidy"
```

`renamed` takes a mapping (or a function) and rewrites every state name, `StartAt` and the transitions that follow it,
including inside `Map` and `Parallel`. `map_states` applies one change to the states you choose. Both return a new
fragment, so the port itself stays as it was.

The test states what changes, in full:

```python
def test_tidy_changes_what_it_says() -> None:
    original = json.loads(Path("original.json").read_text())
    expected = Fragment(original["StartAt"], original["States"]).renamed(RENAMES).build()
    assert find_machine_differences(build(), expected) == [
        'States.Check_ReconcileStatus.Catch[0].Next: "Perform_ReconcileFailed", expected "Common_Failed"',
        'States.Fetch_Accounts.Catch[0].Next: "Perform_ReconcileFailed", expected "Perform_ImportFailed"',
    ]
```

That list is the change description for the review: two error routes are fixed and one name is spelled correctly.
Anything else in it is a bug in the tidy-up. When the original is also renamed, a rename shows up in neither list, so
the list contains only behaviour changes.

## Step 4: keep it honest afterwards

- **Keep `original.json` and the verbatim test** while the old machine is still deployed anywhere. When it is gone, the
  tidy version becomes the golden file: commit the rendered machine and let CI fail when it changes
  ([`assert_matches_file`](../testing.md)).
- **Check the template too.** `assert_state_machines_valid(template)` runs the graph check on what you actually deploy,
  and `find_all_problems` reports it as `asl`.
- **Draw it for review.** `to_mermaid(definition)` writes a diagram you can paste into a pull request. A change to the
  graph shows up as a change to the picture.

## Where the line is

| In `cfn_typed.asl` | In your port |
|---|---|
| typed states, `rule`, `choice`, `wait`, `retry`, `catch` | `task()`: which Lambda, which retry set, where errors go |
| `Fragment`, `Exit`, `wire`, `include`, `prefixed`, `renamed`, `map_states` | what an operation is, and what `succeeded` and `failed` mean |
| `find_asl_problems`, `build()` | the polling loop, with your flag names and defaults |
| `find_machine_differences`, `assert_same_machine` | the list of expected differences for each step |
| `substituted`, `to_mermaid` | your naming conventions |

If you find yourself writing the same helper in two projects, that is the sign it may belong in the library. Open an
issue with the helper and the shapes it covers.
