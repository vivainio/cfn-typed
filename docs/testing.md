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

## Keeping the output deterministic

The check is exact, so the generator must render the same text every time. The library already
keeps keys in insertion order and never emits YAML anchors. What remains is up to your code:

- Do not put timestamps, random values or the current user in a template.
- Do not iterate a `set` or an unsorted directory listing to build resources; sort first.
- Take inputs such as the stage as **arguments**, as `build("prod")` does, rather than reading
  the environment inside the stack.

These are the same rules that keep a generator [easy to reason about](index.md); the golden
test just enforces them.

## What it does and does not check

A golden file proves the code renders what you committed. It does not prove that CloudFormation
accepts it. Keep `cfn-lint` (or a change set against a test account) in CI as well, and run it
over the same committed files.

The rendered files are also the natural place to follow the migration advice from the
[Jsonnet comparison](https://vivainio.github.io/articles/infrastructure/python-typeddict-cloudformation/):
render the old template and the new one, diff them, and expect an empty change set.
