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
from datetime import date
from pathlib import Path
from types import ModuleType
from typing import Any

from cfn_typed.attributes import find_attribute_problems
from cfn_typed.checks import find_all_problems
from cfn_typed.combinations import find_combination_problems
from cfn_typed.constraints import find_constraint_problems
from cfn_typed.iam import find_iam_problems
from cfn_typed.lifecycle import find_lifecycle_problems
from cfn_typed.limits import find_limit_problems
from cfn_typed.references import find_reference_problems, find_unused_problems
from cfn_typed.render import to_json, to_yaml
from cfn_typed.values import find_value_problems

UPDATE_ENV = "CFN_TYPED_UPDATE"


def render_for(path: Path, template: Mapping[str, Any], indent: int | str | None = 2) -> str:
    """The text a golden file at `path` should contain: JSON for `.json`, YAML otherwise. `indent` is for JSON only."""
    return to_json(template, indent) + "\n" if path.suffix == ".json" else to_yaml(template)


def assert_matches_file(
    template: Mapping[str, Any], path: str | Path, *, update: bool | None = None, indent: int | str | None = 2,
) -> None:
    """Fail unless rendering `template` gives exactly the contents of `path`.

    With `update=True` (or `CFN_TYPED_UPDATE=1` in the environment) the file is written instead.
    A missing file is a failure, so CI never creates golden files by itself.
    `indent` is the JSON indent as in `to_json`, for a repository whose JSON files are indented with tabs.
    """
    path = Path(path)
    actual = render_for(path, template, indent)
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


def assert_constraints_hold(template: Mapping[str, Any], types: ModuleType | Mapping[str, Any], *, defaults: bool = True) -> None:
    """Fail if a property value breaks a constraint from the registry schemas: allowed values, pattern, length, range, item count.

    `types` is the package `cfn-typegen` generated. Intrinsics are followed where the template decides their value.
    CloudFormation reports these only at deploy time. See `cfn_typed.constraints` for what is and is not checked.
    """
    problems = find_constraint_problems(template, types, defaults=defaults)
    if problems:
        raise AssertionError("the template has values outside the schema's constraints:\n" + "\n".join(f"  {p}" for p in problems))


def assert_attributes_exist(template: Mapping[str, Any], types: ModuleType | Mapping[str, Any]) -> None:
    """Fail if an `Fn::GetAtt` asks a resource for an attribute its type does not have.

    `types` is the package `cfn-typegen` generated. CloudFormation reports this only at deploy time. See `cfn_typed.attributes`.
    """
    problems = find_attribute_problems(template, types)
    if problems:
        raise AssertionError("the template asks for attributes that do not exist:\n" + "\n".join(f"  {p}" for p in problems))


def assert_combinations_valid(template: Mapping[str, Any], types: ModuleType | Mapping[str, Any]) -> None:
    """Fail if properties are set in a combination the schemas rule out: not exactly one of X or Y, or A set without B.

    `types` is the package `cfn-typegen` generated. CloudFormation reports this only at deploy time. See `cfn_typed.combinations`.
    """
    problems = find_combination_problems(template, types)
    if problems:
        raise AssertionError("the template sets properties in a combination the schema rules out:\n" + "\n".join(f"  {p}" for p in problems))


def assert_values_valid(template: Mapping[str, Any], *, defaults: bool = True) -> None:
    """Fail on an `Fn::FindInMap` key the mapping lacks, an `Fn::Select` index outside its list, or a parameter default its own constraints reject. See `cfn_typed.values`."""
    problems = find_value_problems(template, defaults=defaults)
    if problems:
        raise AssertionError("the template looks up or declares values that are wrong:\n" + "\n".join(f"  {p}" for p in problems))


def assert_iam_valid(template: Mapping[str, Any]) -> None:
    """Fail on an IAM action that does not exist, a resource of the wrong service, or an S3 bucket/object ARN mix-up. See `cfn_typed.iam`."""
    problems = find_iam_problems(template)
    if problems:
        raise AssertionError("the template has IAM statements that look wrong:\n" + "\n".join(f"  {p}" for p in problems))


def assert_runtimes_supported(template: Mapping[str, Any], *, today: date | None = None, defaults: bool = True) -> None:
    """Fail if a Lambda function uses a runtime AWS has deprecated. See `cfn_typed.lifecycle`."""
    problems = find_lifecycle_problems(template, today=today, defaults=defaults)
    if problems:
        raise AssertionError("the template uses deprecated Lambda runtimes:\n" + "\n".join(f"  {p}" for p in problems))


def assert_within_limits(template: Mapping[str, Any], *, inline: bool = False) -> None:
    """Fail if the template breaks a CloudFormation quota or naming rule. See `cfn_typed.limits`."""
    problems = find_limit_problems(template, inline=inline)
    if problems:
        raise AssertionError("the template is outside CloudFormation's limits:\n" + "\n".join(f"  {p}" for p in problems))


def assert_nothing_unused(template: Mapping[str, Any]) -> None:
    """Fail if a parameter, condition or mapping is never referred to. See `cfn_typed.references.find_unused_problems`."""
    problems = find_unused_problems(template)
    if problems:
        raise AssertionError("the template has unused definitions:\n" + "\n".join(f"  {p}" for p in problems))


def assert_template_ok(
    template: Mapping[str, Any], types: ModuleType | None = None, *, inline: bool = False, unused: bool = True, defaults: bool = True, today: date | None = None
) -> None:
    """Fail if any check finds a problem: references, unused definitions, limits and, given `types`, constraints and attributes.

    The one call to put in a test. Each problem is listed under the check that found it. See `cfn_typed.checks`.
    """
    found = find_all_problems(template, types, inline=inline, unused=unused, defaults=defaults, today=today)
    if found:
        lines = [f"  [{check}] {p}" for check, problems in found.items() for p in problems]
        raise AssertionError("the template has problems:\n" + "\n".join(lines))
