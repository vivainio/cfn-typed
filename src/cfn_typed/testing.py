"""Golden-file checks: commit the rendered template, and fail when the code renders something else.

    def test_orders_stack() -> None:
        assert_matches_file(build("prod"), Path("rendered/orders-prod.yaml"))

A template change then shows up as a line diff in the pull request, and CI fails if the
committed file and the code disagree. To accept an intended change, rerun the tests with
`CFN_TYPED_UPDATE=1`, which rewrites the files instead of failing, and commit the result.
"""

import difflib
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from cfn_typed.references import find_reference_problems
from cfn_typed.render import to_json, to_yaml

UPDATE_ENV = "CFN_TYPED_UPDATE"


def render_for(path: Path, template: Mapping[str, Any]) -> str:
    """The text a golden file at `path` should contain: JSON for `.json`, YAML otherwise."""
    return to_json(template) + "\n" if path.suffix == ".json" else to_yaml(template)


def assert_matches_file(template: Mapping[str, Any], path: str | Path, *, update: bool | None = None) -> None:
    """Fail unless rendering `template` gives exactly the contents of `path`.

    With `update=True` (or `CFN_TYPED_UPDATE=1` in the environment) the file is written instead.
    A missing file is a failure, so CI never creates golden files by itself.
    """
    path = Path(path)
    actual = render_for(path, template)
    if update is None:
        update = os.environ.get(UPDATE_ENV) == "1"
    if update:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists() or path.read_text() != actual:
            path.write_text(actual)
        return
    hint = f"If the change is intended, regenerate with {UPDATE_ENV}=1 and commit the result."
    if not path.exists():
        raise AssertionError(f"{path} does not exist. Create it with {UPDATE_ENV}=1 and commit it.")
    expected = path.read_text()
    if expected != actual:
        diff = "".join(difflib.unified_diff(expected.splitlines(True), actual.splitlines(True), str(path), "rendered", n=3))
        raise AssertionError(f"the rendered template differs from {path}:\n{diff}\n{hint}")


def assert_references_resolve(template: Mapping[str, Any]) -> None:
    """Fail if the template refers to a resource, parameter, condition or mapping that does not exist, or has a dependency cycle.

    CloudFormation reports these only at deploy time. See `cfn_typed.references` for what is checked.
    """
    problems = find_reference_problems(template)
    if problems:
        raise AssertionError("the template has unresolved references:\n" + "\n".join(f"  {p}" for p in problems))
