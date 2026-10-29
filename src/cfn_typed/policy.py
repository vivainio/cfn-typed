"""IAM policy statements: `allow` and `deny`, principals, and conditions.

    from cfn_typed import allow, deny
    from cfn_typed.policy import ANY, aws, bool_, string_not_like

    allow(["sqs:ReceiveMessage"], queue_arn)                               # identity policy: no principal
    allow("kms:*", "*", sid="EnableIam", principal=aws(root_arn))          # key policy: Resource is "*"
    deny("s3:*", [bucket_arn], principal=ANY, condition=bool_("aws:SecureTransport", False))

Statements are plain dicts in the order IAM documents (Sid, Effect, Principal, Action, Resource, Condition), so
the rendered template reads like a policy. Nothing here is opinion: it builds what you describe. Which actions
belong together is the job of `cfn_typed.grants`.
"""

from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Final, Literal, NotRequired, TypedDict, Unpack, cast

from cfn_typed.intrinsics import Expr

ANY: Final = "*"  # every principal, as in `Principal: "*"`


class PrincipalMap(TypedDict):
    AWS: NotRequired[Expr[str] | list[Expr[str]]]
    Service: NotRequired[Expr[str] | list[Expr[str]]]
    Federated: NotRequired[Expr[str] | list[Expr[str]]]
    CanonicalUser: NotRequired[Expr[str] | list[Expr[str]]]


type Principal = Literal["*"] | PrincipalMap
type Condition = Mapping[str, Mapping[str, Expr[str] | list[Expr[str]]]]


class Statement(TypedDict):
    Sid: NotRequired[str]
    Effect: Literal["Allow", "Deny"]
    Principal: NotRequired[Principal]
    Action: str | list[str]
    Resource: NotRequired[Expr[str] | list[Expr[str]]]
    Condition: NotRequired[Condition]


class PolicyDocument(TypedDict):
    Version: Literal["2012-10-17"]
    Statement: list[Statement]


def policy_document(statements: Iterable[Statement]) -> PolicyDocument:
    """A policy document for a role's inline policy, a managed policy, a bucket policy, ..."""
    return {"Version": "2012-10-17", "Statement": list(statements)}


# -- principals ------------------------------------------------------------------------------------------------


def _one_or_many(values: tuple[Expr[str], ...]) -> Expr[str] | list[Expr[str]]:
    if not values:
        raise ValueError("a principal needs at least one value")
    if len(values) == 1:
        return values[0]  # IAM accepts either; one value reads best as a scalar
    many: list[Expr[str]] = list(values)
    return many


def aws(*arns: Expr[str]) -> PrincipalMap:
    """AWS principals: accounts, roles, users. One ARN is written as a scalar, several as a list."""
    return {"AWS": _one_or_many(arns)}


def service(*names: Expr[str]) -> PrincipalMap:
    """Service principals, such as `lambda.amazonaws.com`."""
    return {"Service": _one_or_many(names)}


# -- statements ------------------------------------------------------------------------------------------------


def _statement(
    effect: Literal["Allow", "Deny"],
    actions: str | Sequence[str],
    resource: Expr[str] | list[Expr[str]] | None,
    sid: str | None,
    principal: Principal | None,
    condition: Condition | None,
) -> Statement:
    parts: list[tuple[str, Any]] = [
        ("Sid", sid),
        ("Effect", effect),
        ("Principal", principal),
        ("Action", actions if isinstance(actions, str) else list(actions)),
        ("Resource", resource),
        ("Condition", condition),
    ]
    return cast(Statement, {key: value for key, value in parts if value is not None})


def allow(
    actions: str | Sequence[str],
    resource: Expr[str] | list[Expr[str]] | None = None,
    *,
    sid: str | None = None,
    principal: Principal | None = None,
    condition: Condition | None = None,
) -> Statement:
    """An `Allow` statement. Leave out `principal` for an identity policy, and `resource` where the policy is
    attached to what it protects and the field is not allowed (an ECR repository policy)."""
    return _statement("Allow", actions, resource, sid, principal, condition)


def deny(
    actions: str | Sequence[str],
    resource: Expr[str] | list[Expr[str]] | None = None,
    *,
    sid: str | None = None,
    principal: Principal | None = None,
    condition: Condition | None = None,
) -> Statement:
    """A `Deny` statement. An explicit deny beats every allow, wherever the allow comes from."""
    return _statement("Deny", actions, resource, sid, principal, condition)


# -- conditions ------------------------------------------------------------------------------------------------

Operator = Literal[
    "StringEquals", "StringNotEquals", "StringEqualsIgnoreCase", "StringNotEqualsIgnoreCase", "StringLike", "StringNotLike",
    "NumericEquals", "NumericNotEquals", "NumericLessThan", "NumericLessThanEquals", "NumericGreaterThan", "NumericGreaterThanEquals",
    "DateEquals", "DateNotEquals", "DateLessThan", "DateLessThanEquals", "DateGreaterThan", "DateGreaterThanEquals",
    "Bool", "BinaryEquals", "IpAddress", "NotIpAddress", "ArnEquals", "ArnLike", "ArnNotEquals", "ArnNotLike", "Null",
]


class Qualifiers(TypedDict):
    for_any_value: NotRequired[bool]
    for_all_values: NotRequired[bool]
    if_exists: NotRequired[bool]


class GlobalKeys:
    """A short, hand-picked list of global condition keys, those the examples and the AWS CDK use. Not complete:
    for any other key, write the string."""

    PrincipalArn: Final = "aws:PrincipalArn"
    PrincipalOrgID: Final = "aws:PrincipalOrgID"
    SecureTransport: Final = "aws:SecureTransport"
    SourceAccount: Final = "aws:SourceAccount"
    SourceArn: Final = "aws:SourceArn"


def _scalar(value: Any) -> Expr[str]:
    if isinstance(value, bool):  # IAM compares these as the strings "true" and "false"
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, (str, dict)):  # a string, or an intrinsic such as a Ref
        return value
    raise TypeError(f"a condition value is a string, number, bool or intrinsic, got {type(value).__name__}")


def _values(value: Any) -> Expr[str] | list[Expr[str]]:
    if isinstance(value, (bool, int, str, dict)):
        return _scalar(value)
    return [_scalar(v) for v in value]


def condition(
    operator: Operator,
    key: str,
    values: Expr[str] | bool | int | Sequence[Expr[str]],
    *,
    for_any_value: bool = False,
    for_all_values: bool = False,
    if_exists: bool = False,
) -> Condition:
    """One condition: `condition("StringEquals", "aws:SourceAccount", account_id)`.

    `for_any_value` / `for_all_values` add the multi-value qualifiers, and `if_exists` the `IfExists` suffix.
    Booleans and integers become the strings IAM compares.
    """
    if for_any_value and for_all_values:
        raise ValueError("a condition is either ForAnyValue or ForAllValues")
    if if_exists and operator == "Null":
        raise ValueError("IfExists cannot be used with Null")
    name = operator + ("IfExists" if if_exists else "")
    if for_any_value:
        name = "ForAnyValue:" + name
    elif for_all_values:
        name = "ForAllValues:" + name
    return {name: {key: _values(values)}}


def string_equals(key: str, values: Expr[str] | Sequence[Expr[str]], **q: Unpack[Qualifiers]) -> Condition:
    return condition("StringEquals", key, values, **q)


def string_not_equals(key: str, values: Expr[str] | Sequence[Expr[str]], **q: Unpack[Qualifiers]) -> Condition:
    return condition("StringNotEquals", key, values, **q)


def string_like(key: str, values: Expr[str] | Sequence[Expr[str]], **q: Unpack[Qualifiers]) -> Condition:
    return condition("StringLike", key, values, **q)


def string_not_like(key: str, values: Expr[str] | Sequence[Expr[str]], **q: Unpack[Qualifiers]) -> Condition:
    return condition("StringNotLike", key, values, **q)


def arn_equals(key: str, values: Expr[str] | Sequence[Expr[str]], **q: Unpack[Qualifiers]) -> Condition:
    return condition("ArnEquals", key, values, **q)


def arn_like(key: str, values: Expr[str] | Sequence[Expr[str]], **q: Unpack[Qualifiers]) -> Condition:
    return condition("ArnLike", key, values, **q)


def bool_(key: str, value: bool, **q: Unpack[Qualifiers]) -> Condition:
    return condition("Bool", key, value, **q)


def ip_address(key: str, cidrs: Expr[str] | Sequence[Expr[str]], **q: Unpack[Qualifiers]) -> Condition:
    return condition("IpAddress", key, cidrs, **q)


def merge_conditions(*conditions: Condition) -> Condition:
    """Combine conditions; all of them must hold. The same operator and key twice is an error, not a silent overwrite."""
    merged: dict[str, dict[str, Expr[str] | list[Expr[str]]]] = {}
    for one in conditions:
        for operator, keys in one.items():
            target = merged.setdefault(operator, {})
            for key, value in keys.items():
                if key in target:
                    raise ValueError(f"condition {operator} on {key} is given twice")
                target[key] = value
    return merged
