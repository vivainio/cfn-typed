# Testing with golden templates

A template is plain data, so the strongest test is also the simplest: **commit the rendered
YAML, and have CI check that your code still renders exactly that.**

```text
rendered/
  orders-prod.yaml      # committed
  orders-dev.yaml
tests/
  test_rendered.py      # renders each stack and compares
```

```python
from pathlib import Path

from cfn_typed.testing import assert_matches_file

from orders import build


def test_orders_prod() -> None:
    assert_matches_file(build("prod"), Path("rendered/orders-prod.yaml"))
```

## What you get

- **Infrastructure changes show up in code review.** A pull request that changes a default,
  a pattern or a parameter also changes the rendered file, so the reviewer sees the exact
  CloudFormation lines that will change, not only the Python that produces them.
- **Accidental changes fail CI.** Edit a shared helper and forget that three stacks use it, and
  the other two stacks' files no longer match. Here a pattern's default idle timeout was
  changed from 60 to 300 seconds, and the test for the stack that uses it fails with:

    ```diff
    --- examples/rendered/web-stack.yaml
    +++ rendered
    @@ -35,7 +35,7 @@
             - !Ref WebSecurityGroup
           LoadBalancerAttributes:
             - Key: idle_timeout.timeout_seconds
    -          Value: '60'
    +          Value: '300'
    ```

- **A refactor that should change nothing proves it.** Restructure a pattern, run the tests,
  and an unchanged set of golden files shows that the output is identical.

## Make it part of your CI

Do this in every repository that renders templates with `cfn-typed`. It is one test file and a
few lines of workflow, and it turns every template change into a reviewed diff. A GitHub
Actions workflow (this repository's own CI is the same shape):

```yaml
name: CI
on:
  push:
    branches: [main]
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: astral-sh/setup-uv@v7
      - run: uv sync
      # only if you generate the types in CI rather than committing them:
      - run: uv run cfn-typegen        # reads cfn-typegen.toml
      - run: uv run ty check
      - run: uv run pytest        # includes the golden-template tests
```

`pytest` fails when a rendered file differs from the code or is missing, which is the whole
check. Run it on pull requests as well as on `main`, so the diff is reviewed *before* the
change lands, and commit the regenerated files in the same pull request as the code change.

Two habits that make it dependable:

- **Pin your tool versions.** The YAML text comes from PyYAML, so an upgrade that changes its
  formatting would show up as a diff in every golden file. Commit your lock file (`uv.lock`) so CI
  and your laptop render with the same versions, and upgrade `cfn-typed` and `pyyaml` on purpose,
  in their own pull request.
- **One file per stack and stage.** `orders-dev.yaml` and `orders-prod.yaml` side by side make
  the difference between environments something you can read.

If you also run `cfn-lint`, point it at the committed files in the same job.

## Accepting an intended change

When the diff is what you meant, regenerate the files and commit them with the code change:

```sh
CFN_TYPED_UPDATE=1 uv run pytest
git diff rendered/        # review it
```

With that variable set, `assert_matches_file` writes the file instead of failing. Without it,
a **missing file is a failure**, so CI can never quietly create the golden files it is supposed
to compare against.

The file type follows the name: `.yaml` is rendered with `to_yaml`, `.json` with `to_json`.

JSON is indented with two spaces. A repository whose JSON files use tabs passes the indent through:
`assert_matches_file(template, "rendered/stack.json", indent="\t")`, and `to_json(template, indent="\t")` renders
the same text. `indent` is as in `json.dumps`.

## Keeping the output deterministic

The check is exact, so the generator must render the same text every time. The library already
keeps keys in insertion order and never emits YAML anchors. What remains is up to your code:

- Do not put timestamps, random values or the current user in a template.
- Do not iterate a `set` or an unsorted directory listing to build resources; sort first.
- Take inputs such as the stage as **arguments**, as `build("prod")` does, rather than reading
  the environment inside the stack.

These are the same rules that keep a generator easy to reason about; the golden test just
enforces them.

## Checking that references resolve

A logical ID is a plain string wherever you use it, so `ref("Jbos")` renders without complaint
and fails at deploy time. `assert_references_resolve` walks the finished template, which also
covers fragments that were [combined](patterns/composing.md) from patterns:

```python
from cfn_typed.testing import assert_references_resolve

def test_orders_references() -> None:
    assert_references_resolve(build("prod"))
```

```text
AssertionError: the template has unresolved references:
  Resources.Worker.Properties.Role: Fn::GetAtt refers to 'ExecutionRol', which is not a resource (did you mean 'ExecutionRole'?)
  Resources: circular dependency Api -> Authorizer -> Api
```

It checks `Ref`, `Fn::GetAtt`, `${Name}` in `Fn::Sub`, `DependsOn`, condition names (on a
resource, an output, `Fn::If` and inside a condition) and `Fn::FindInMap` map names, and it
reports dependency cycles. Pseudo parameters such as `AWS::Region` always resolve. Use
`cfn_typed.references.find_reference_problems(template)` to get the messages as a list.

It does not check that a `GetAtt` attribute exists on its resource type.

## Checking values against the schema

The registry schemas also say which values a property accepts: a fixed set, a pattern, a
length, a range, a number of items. The type checker cannot see those, so a bad value renders
fine and fails at deploy time. `assert_constraints_hold` checks them against the types
`cfn-typegen` generated:

```python
import acme_cfn  # the generated package
from cfn_typed.testing import assert_constraints_hold

def test_orders_stack() -> None:
    assert_constraints_hold(build("prod"), acme_cfn)
```

```text
Resources.Logs.Properties.RetentionInDays: 13 is not one of 1, 3, 5, 7, 14, 30, 60, 90, ... (Ref Retention, default)
Resources.Q.Properties.RedrivePolicy.maxReceiveCount: 0 is less than the minimum of 1
```

Only the services the template uses are imported, and a numeric string such as `"443"` is
checked as a number. A value an intrinsic produces is checked where the template decides it:

| Value | Checked |
|---|---|
| `Ref` to a parameter | each of its `AllowedValues`, else its `Default` (`defaults=False` leaves defaults out) |
| `Fn::If` | both branches |
| `Fn::FindInMap` | the entry for literal keys, else every entry under the unknown key |
| `Fn::Sub`, `Fn::Join`, `Fn::Select`, `Fn::Split` | the result, when every piece is known as above |
| `Ref` to a resource or pseudo parameter, `Fn::GetAtt`, `Fn::ImportValue`, `Fn::GetAZs`, SSM-typed parameters, `{{resolve:...}}` | skipped: decided at deploy time |

A `Default` that is only a placeholder behind an `Fn::If` is reported too. Pass
`defaults=False`, or keep the value out of the parameter's `Default`. Use
`cfn_typed.constraints.find_constraint_problems(template, types)` to get the messages as a list.

The registry constrains only what AWS modelled: about 1,500 of 1,870 resource types have at
least one constrained property, and many common ones (an S3 bucket name, a DynamoDB billing
mode) have none. It is also sometimes stricter than CloudFormation; see `unconstrained` on
[the generator page](generator.md#configuration-file).

## More checks on the finished template

```python
from cfn_typed.testing import assert_attributes_exist, assert_combinations_valid, assert_iam_valid, assert_nothing_unused, assert_runtimes_supported, assert_state_machines_valid, assert_values_valid, assert_within_limits

def test_orders_checks() -> None:
    template = build("prod")
    assert_attributes_exist(template, acme_cfn)   # GetAtt names an attribute the type has
    assert_combinations_valid(template, acme_cfn) # exactly one of X or Y, A needs B
    assert_values_valid(template)                 # FindInMap keys, Select indexes, parameter defaults
    assert_runtimes_supported(template)           # no deprecated Lambda runtime
    assert_iam_valid(template)                    # known actions, matching resources, S3 bucket vs object ARN
    assert_within_limits(template)                # 500 resources, 200 parameters, logical ID names, size
    assert_nothing_unused(template)               # no idle parameter, condition or mapping
    assert_state_machines_valid(template)         # Next/Catch targets exist, nothing unreachable, no loop without exit
```

To run all of them at once, `assert_template_ok(template, acme_cfn)` calls every check and lists each problem under
the check that found it (`[references]`, `[unused]`, `[limits]`, `[constraints]`, `[attributes]`, `[combinations]`, `[values]`, `[lifecycle]`, `[iam]`, `[asl]`, and one per company rule); leave out `types`
to skip the two schema checks, or pass `unused=False`. `find_all_problems` returns the same as a dict.

`assert_combinations_valid` reads the `RULES` table: the registry's `oneOf`, `anyOf` and `dependencies` where they say which
properties must be set (about 150 rules on 100 resource types, 18 KB for all of them). A property is unset when it is
`Ref: AWS::NoValue` and maybe set when only one `Fn::If` branch is, and a rule is reported only when it is broken either way.

`assert_iam_valid` links each statement to the action lists in `cfn_typed.permissions` (12 services; others are left alone):
the service of a resource type (`AWS::SQS::Queue` is `sqs`) is matched against the statement's action prefixes, and S3 object
actions are told apart from bucket actions. `assert_runtimes_supported` uses support dates copied from cfn-lint
(`scripts/sync-lambda-runtimes.py` refreshes them), so it goes stale like any data.

`assert_attributes_exist` reads the `ATTRIBUTES` table that `cfn-typegen` writes next to `CONSTRAINTS`
(read-only and identifier properties, `Outer.Inner` for nested ones). `assert_references_resolve` also fails when a
resource without a `Condition` refers to one that has it, unless an `Fn::If` or an `Fn::And` condition guards the reference.

A company's own rules go in the same call: `assert_template_ok(template, acme_cfn, rules=COMPANY_RULES)`. See
[Company rules](patterns/company-rules.md).

## What it does and does not check

A golden file proves the code renders what you committed. It does not prove that CloudFormation
accepts it. Keep `cfn-lint` (or a change set against a test account) in CI as well, and run it
over the same committed files.

The rendered files are also the natural place to follow the migration advice from the
[Jsonnet comparison](https://vivainio.github.io/articles/infrastructure/python-typeddict-cloudformation/):
render the old template and the new one, diff them, and expect an empty change set.

## State machines

`cfn_typed.asl` has the ASL spec as closed `TypedDict`s (`Definition`, `TaskState`, `ChoiceState`, `MapState`, ...), so
a misspelled key or a `Choice` with a `Next` is an error in the editor, and `find_asl_problems(definition)` checks
the graph: every `Next`, `Default` and `Catch` target exists in its scope (a `Parallel` branch or `Map` item processor
is its own scope), names are unique, nothing is unreachable, every state can reach an end, `Retry` and `Catch` entries
are well formed (`States.ALL` alone and last, known `States.*` names, numbers in range), and a `Wait` has exactly one
duration. It reads a `Definition` object, or a literal `DefinitionString` (a plain JSON string, or `Fn::Sub` of one);
a definition built with other intrinsics cannot be read and is skipped. `assert_state_machine_valid(definition)` and
`assert_state_machines_valid(template)` fail with one line per problem.

### Reuse in a big machine

`cfn_typed.asl.Fragment` is a piece of graph with named open exits. Put `Exit("done")` where a state name goes, and a
state that needs a `Next` and has none gets `Exit("next")`:

- `step(name, state)` is a fragment of one state; `chain(a, b, c)` and `a.then(b)` wire `next` to the following start.
- `frag.wire("done", "Handler")` or `frag.wire("done", other_fragment)` points every exit of that name at a state, or at
  a fragment (whose states are added). `frag.end()` finishes at a plain `Next` with `End: true`.
- `frag.prefixed("Tenant_")` renames every state and the transitions between them, so one pattern can be used twice
  (names are unique across a whole machine). `frag.include(other)` adds states nothing leads to yet, such as a shared
  failure handler that other states name.
- `frag.map_states(fn, where="Task")` applies a policy, such as a `Catch` or a retry set, to every matching state.
- `frag.build(Comment=...)` returns the `Definition`, and refuses open exits or a graph `find_asl_problems` rejects.

Fragments never change; each method returns a new one. A polling loop or a shared retry policy is an ordinary
function that returns a fragment: the library has no opinion on what one looks like.

To refactor an existing machine, check that the new one is the old one: `assert_same_machine(built, original)` (or
`find_machine_differences`) lists each difference and ignores key order. `to_mermaid(definition)` returns
[Mermaid](https://mermaid.js.org) source for the graph, to review a machine of hundreds of states.

To start from an existing machine,
`cfn-typed import --asl` writes each `DefinitionString` as a `Definition` object (the output then differs
from the original template in that property, so the exact round trip does not hold for it).
