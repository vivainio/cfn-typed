"""Write a company's rules as data instead of loops.

    COMPANY_RULES = [
        require("AWS::S3::Bucket", "BucketEncryption"),
        require("AWS::S3::Bucket", "PublicAccessBlockConfiguration.BlockPublicAcls", equals=True),
        require("AWS::Logs::LogGroup", "RetentionInDays", at_least=30),
        forbid("AWS::S3::Bucket", "AccessControl", one_of=["PublicRead", "PublicReadWrite"]),
    ]
    assert_template_ok(template, rules=COMPANY_RULES)

Each constructor returns a `Rule` (template in, problems out), named after what it demands, so a failure reads
`[AWS::S3::Bucket.BucketEncryption required] Bucket: BucketEncryption is not set`. `types` is one type or a sequence of them,
`path` is as in `cfn_typed.query.prop`, and `unless(logical_id, resource)` exempts a resource.

The value conditions (`equals`, `one_of`, `at_least`, `at_most`, `matches`) are all optional and all must hold. A value the template
leaves to deploy time (a `Ref`, `Fn::If`, `Fn::GetAtt`, and so on) counts as set but cannot be compared, so it is accepted:
a rule is silent about what it cannot read. `each` is for logic the constructors do not cover.
"""

import re
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from cfn_typed.checks import Rule
from cfn_typed.query import prop, resources_of

type Exempt = Callable[[str, Mapping[str, Any]], bool]


def _types(types: str | Sequence[str]) -> tuple[str, ...]:
    return (types,) if isinstance(types, str) else tuple(types)


def _unknown(value: Any) -> bool:
    return isinstance(value, Mapping) and len(value) == 1 and next(iter(value)).startswith(("Ref", "Fn::"))


def _failures(value: Any, equals: Any, one_of: Sequence[Any] | None, at_least: float | None, at_most: float | None, matches: str | None) -> list[str]:
    """What is wrong with `value` against the conditions, as the end of a sentence like 'expected ...'."""
    out: list[str] = []
    if equals is not None and value != equals:
        out.append(f"{equals!r}")
    if one_of is not None and value not in one_of:
        out.append(f"one of {', '.join(map(repr, one_of))}")
    number = isinstance(value, int | float) and not isinstance(value, bool)
    if at_least is not None and not (number and value >= at_least):
        out.append(f"at least {at_least}")
    if at_most is not None and not (number and value <= at_most):
        out.append(f"at most {at_most}")
    if matches is not None and not (isinstance(value, str) and re.fullmatch(matches, value)):
        out.append(f"to match {matches}")
    return out


def _describe(path: str, equals: Any, one_of: Any, at_least: Any, at_most: Any, matches: Any) -> str:
    conds = [f"{n}={v!r}" for n, v in (("equals", equals), ("one_of", one_of), ("at_least", at_least), ("at_most", at_most), ("matches", matches)) if v is not None]
    return f"{path} {' '.join(conds)}" if conds else path


def require(
    types: str | Sequence[str],
    path: str,
    *,
    equals: Any = None,
    one_of: Sequence[Any] | None = None,
    at_least: float | None = None,
    at_most: float | None = None,
    matches: str | None = None,
    unless: Exempt | None = None,
) -> Rule:
    """Every resource of `types` sets `path`, and its value meets the conditions."""
    wanted = _types(types)

    def rule(template: Mapping[str, Any]) -> list[str]:
        out: list[str] = []
        for logical_id, resource in resources_of(template, *wanted).items():
            if unless and unless(logical_id, resource):
                continue
            value = prop(resource, path)
            if value is None:
                out.append(f"{logical_id}: {path} is not set")
            elif not _unknown(value) and (bad := _failures(value, equals, one_of, at_least, at_most, matches)):
                out.append(f"{logical_id}: {path} is {value!r}, expected {' and '.join(bad)}")
        return out

    rule.__name__ = f"{'|'.join(wanted)}.{_describe(path, equals, one_of, at_least, at_most, matches)} required"
    return rule


def forbid(
    types: str | Sequence[str],
    path: str,
    *,
    equals: Any = None,
    one_of: Sequence[Any] | None = None,
    unless: Exempt | None = None,
) -> Rule:
    """No resource of `types` sets `path`, or with `equals` / `one_of`, sets it to that value."""
    wanted = _types(types)

    def rule(template: Mapping[str, Any]) -> list[str]:
        out: list[str] = []
        for logical_id, resource in resources_of(template, *wanted).items():
            if unless and unless(logical_id, resource):
                continue
            value = prop(resource, path)
            if value is None or _unknown(value):
                continue
            if (equals is None and one_of is None) or value == equals or (one_of is not None and value in one_of):
                out.append(f"{logical_id}: {path} is {value!r}, which is not allowed")
        return out

    rule.__name__ = f"{'|'.join(wanted)}.{_describe(path, equals, one_of, None, None, None)} forbidden"
    return rule


def each(*types: str) -> Callable[[Callable[[str, Mapping[str, Any]], str | Sequence[str] | None]], Rule]:
    """Turn a function of one resource into a rule over every resource of `types`.

        @each("AWS::SQS::Queue")
        def named_by_convention(logical_id, queue):
            if not logical_id.endswith(("Queue", "DLQ")): return "name ends in neither Queue nor DLQ"

    It returns a problem, a list of them, or `None`. The rule keeps the function's name.
    """

    def wrap(fn: Callable[[str, Mapping[str, Any]], str | Sequence[str] | None]) -> Rule:
        def rule(template: Mapping[str, Any]) -> list[str]:
            out: list[str] = []
            for logical_id, resource in resources_of(template, *types).items():
                found = fn(logical_id, resource)
                out += [f"{logical_id}: {found}"] if isinstance(found, str) else [f"{logical_id}: {p}" for p in found or ()]
            return out

        rule.__name__ = getattr(fn, "__name__", "each")
        return rule

    return wrap
