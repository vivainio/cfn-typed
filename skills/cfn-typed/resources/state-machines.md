# Porting a Step Functions state machine to cfn-typed

Use `cfn_typed.asl` (see the "Step Functions state machines" section of SKILL.md). The book has the full walk-through with
a tested, made-up example: "Working with state machines" (`docs/patterns/state-machines.md` in the cfn-typed repository).

## Procedure

1. **Get the original as JSON and keep it.** `cfn-typed import --asl template.json -o stack.py` writes a template's
   `DefinitionString` as a `Definition` object; or
   `aws stepfunctions describe-state-machine --state-machine-arn ARN --query definition --output text`. It is the oracle
   until the end. Do not commit it if it holds real names (see "Secrets").
2. **Survey before writing.** Count states by type, distinct Task bodies (ignoring `Next`), where `Catch` goes, which
   `Wait`s lead to a `Task` (polling loops), and Tasks with no `Catch`. Few distinct bodies means a `task()` helper pays
   off. States that catch into the same handler form one operation.
3. **Port verbatim.** Every state name kept, every quirk reproduced. One function per operation, returning a `Fragment`.
   Transitions out of an operation are `Exit("succeeded")`, `Exit("error")`, `Exit("failed")` (shared success, shared
   failure, the operation's own handler), wired once at the end: `frag.wire("failed", "Perform_XFailed")`. Assemble a router
   `Fragment` whose `Choice` rules exit as `Exit(action)` and `.wire(action, operation())` each.
4. **Gate on equality.** `assert_same_machine(build(), original)` (lists differences, ignores key order, respects list
   order). Port one operation at a time and compare a subset:
   `fragment.states == {n: original["States"][n] for n in fragment.states}`. `build()` also fails on open exits and unsound
   graphs and names the state.
5. **Then tidy, as reviewable changes.** Renames with `Fragment(d["StartAt"], d["States"]).renamed(MAP)`, bulk edits with
   `.map_states(fn, where=...)`. Test that `find_machine_differences(new, original_renamed_with_the_same_map)` is exactly the list of
   intended behaviour changes; a rename then shows up in neither list.
6. **Deploy path.** Put the definition in `Properties.Definition`, with `cfn_typed.asl.substituted(definition)` wrapping every
   string that holds `${AWS::Region}`, `${Stage}` and the like in `Fn::Sub`. cfn-lint accepts this; `DefinitionSubstitutions` is for
   named placeholders and cfn-lint rejects pseudo parameters left bare. Deploy to a throwaway stack and compare
   `describe-state-machine` with the original before the real one.

## A skeleton

```python
from cfn_typed.asl import Exit, Fragment, catch, choice, retry, rule, step, wait

SUCCEEDED, FAILED, ERROR = Exit("succeeded"), Exit("failed"), Exit("error")
TRANSIENT = [retry("Lambda.ServiceException", "Lambda.TooManyRequestsException")]

def task(next=None, *, retry=TRANSIENT, catch_to=FAILED, end=False):
    s = {"Type": "Task", "Resource": WORKER_ARN}          # WORKER_ARN: your own, e.g. a ${...} template string
    if next: s["Next"] = next
    if end: s["End"] = True
    if retry: s["Retry"] = retry
    if catch_to: s["Catch"] = [catch(catch_to)]
    return s

def import_invoices() -> Fragment:
    return Fragment("Start", {
        "Start": task("Wait_Status"),
        "Wait_Status": wait("Check_Status", seconds=30),
        "Check_Status": task("Verify_Status"),
        "Verify_Status": choice(rule("$.finished", "BooleanEquals", True, SUCCEEDED),
                                rule("$.finished", "BooleanEquals", False, "Wait_Status"), default=ERROR),
        "Perform_Failed": task(ERROR, retry=None, catch_to=None),
    }).wire("failed", "Perform_Failed")

machine = (Fragment("Route", {"Route": choice(rule("$.action", "StringEquals", "Import", Exit("Import")), default=ERROR)})
           .wire("Import", import_invoices())
           .include(step("Done", {"Type": "Succeed"})).include(step("Broken", {"Type": "Fail"}))
           .wire("succeeded", "Done").wire("error", "Broken").build())
```

## What to expect, and what to do

- **Old machines are inconsistent.** One task per operation catches into a different handler, handlers differ from each
  other, names nearly match (`Upscale_`/`UpScale_`), one loop tests `$.finished` where its siblings test `$.continue`.
  Reproduce each in the port under its own exit name or parameter, comment it, and leave the decision to the owner.
  Never "fix" it in the verbatim port: the comparison would fail, and a behaviour change would hide in a refactor.
- **A `Choice` `Default` and a `Catch` are different exits** even in the same state family. Do not merge them.
- **Helpers stay small.** A state that occurs once is a literal dict in its operation. A helper that needs more than three or
  four flags should be two helpers, or leave the odd cases literal. The loop, the retry sets and the task shape belong to the
  user's code, not to the library.
- **Integers stay integers.** `retry(backoff=2)` renders `2`; `2.0` would show in a template diff.
- **State names are consumed elsewhere:** execution history, logs, metrics, X-Ray, alarms, and often the worker Lambda
  (`$$.State.Name`). Search all of them before any rename, and deploy a rename on its own. A running execution keeps the
  definition it started with.
- **Limits:** definition 1 MB; more often 25,000 history events or 256 KB payload bite first. An operation that is already a
  fragment with its own exits can move to a child machine later.

## Secrets

A real definition holds account IDs, Lambda ARNs, bucket names, internal hostnames and sometimes literal secrets in
`Parameters`. Keep the real file out of the repository. Anything committed (fixtures, tests, examples, docs, commit messages)
uses invented names and `${...}` placeholders. Before committing, grep the diff for the real service, customer and account
names, 12-digit numbers and region-specific ARNs.
