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
      - run: uv run cfn-typegen --no-docs --out cfn_types $(grep -v '^#' types.txt)
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
from cfn_typed.testing import assert_attributes_exist, assert_combinations_valid, assert_nothing_unused, assert_within_limits

def test_orders_checks() -> None:
    template = build("prod")
    assert_attributes_exist(template, acme_cfn)   # GetAtt names an attribute the type has
    assert_combinations_valid(template, acme_cfn) # exactly one of X or Y, A needs B
    assert_within_limits(template)                # 500 resources, 200 parameters, logical ID names, size
    assert_nothing_unused(template)               # no idle parameter, condition or mapping
```

To run all of them at once, `assert_template_ok(template, acme_cfn)` calls every check and lists each problem under
the check that found it (`[references]`, `[unused]`, `[limits]`, `[constraints]`, `[attributes]`, `[combinations]`); leave out `types`
to skip the two schema checks, or pass `unused=False`. `find_all_problems` returns the same as a dict.

`assert_combinations_valid` reads the `RULES` table: the registry's `oneOf`, `anyOf` and `dependencies` where they say which
properties must be set (about 150 rules on 100 resource types, 18 KB for all of them). A property is unset when it is
`Ref: AWS::NoValue` and maybe set when only one `Fn::If` branch is, and a rule is reported only when it is broken either way.

`assert_attributes_exist` reads the `ATTRIBUTES` table that `cfn-typegen` writes next to `CONSTRAINTS`
(read-only and identifier properties, `Outer.Inner` for nested ones). `assert_references_resolve` also fails when a
resource without a `Condition` refers to one that has it, unless an `Fn::If` or an `Fn::And` condition guards the reference.

## What it does and does not check

A golden file proves the code renders what you committed. It does not prove that CloudFormation
accepts it. Keep `cfn-lint` (or a change set against a test account) in CI as well, and run it
over the same committed files.

The rendered files are also the natural place to follow the migration advice from the
[Jsonnet comparison](https://vivainio.github.io/articles/infrastructure/python-typeddict-cloudformation/):
render the old template and the new one, diff them, and expect an empty change set.
