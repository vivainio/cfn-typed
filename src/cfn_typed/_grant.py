"""The `Grant` type: a set of IAM actions and the resources they apply to. Use it through `cfn_typed.grants`."""

from dataclasses import dataclass
from typing import Literal

from cfn_typed.helpers import Statement, allow
from cfn_typed.intrinsics import Expr, join

# Which resources a grant applies to, given the ARN you pass to `.on()`:
#   arn              the ARN itself (queue, topic, function, key, secret, ...)
#   arn_and_indexes  the ARN, and with `indexes=True` also `{arn}/index/*` (a DynamoDB table)
#   arn_and_objects  the ARN and the objects under it, `{arn}/{keys}` (an S3 bucket)
#   objects          only the objects under it
#   any              `*`, whatever ARN you have (so none is accepted)
Shape = Literal["arn", "arn_and_indexes", "arn_and_objects", "objects", "any"]


def _child(arn: Expr[str], suffix: str) -> Expr[str]:
    """`{arn}/{suffix}`, also when the ARN is an intrinsic such as a `GetAtt`."""
    return f"{arn}/{suffix}" if isinstance(arn, str) else join("", [arn, f"/{suffix}"])


@dataclass(frozen=True)
class Grant:
    """An immutable set of actions, the actions to add on a customer-managed KMS key, and a resource shape."""

    actions: tuple[str, ...]
    key_actions: tuple[str, ...] = ()
    shape: Shape = "arn"

    def on(
        self,
        arn: Expr[str] | None = None,
        *,
        key_arn: Expr[str] | None = None,
        keys: str | None = None,
        indexes: bool = False,
    ) -> list[Statement]:
        """Identity-policy statements: allow the actions on the resource, plus the key actions on `key_arn`.

        `keys` is the object key pattern for S3 grants (default `*`). `indexes=True` also covers a DynamoDB
        table's indexes. `key_arn` adds the KMS statement for resources encrypted with your own key, and is
        ignored for grants that need none. The statements have no `Principal`: put them in a role's policy,
        a managed policy, or any policy document.
        """
        if self.shape == "any":
            if arn is not None:
                raise ValueError("this grant applies to '*', so it takes no ARN")
        elif arn is None:
            raise ValueError("this grant needs the ARN of the resource")
        if keys is not None and self.shape not in ("arn_and_objects", "objects"):
            raise ValueError("`keys` only applies to grants on objects, such as S3 buckets")
        if indexes and self.shape != "arn_and_indexes":
            raise ValueError("`indexes` only applies to DynamoDB table grants")

        resources: list[Expr[str]]
        if self.shape == "any" or arn is None:
            resources = ["*"]
        elif self.shape == "arn":
            resources = [arn]
        elif self.shape == "arn_and_indexes":
            resources = [arn, _child(arn, "index/*")] if indexes else [arn]
        elif self.shape == "arn_and_objects":
            resources = [arn, _child(arn, keys or "*")]
        else:  # objects
            resources = [_child(arn, keys or "*")]

        statements = [allow(list(self.actions), resources)]
        if self.key_actions and key_arn is not None:
            statements.append(allow(list(self.key_actions), key_arn))
        return statements
