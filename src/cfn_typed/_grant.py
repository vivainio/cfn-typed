"""The `Grant` type: a set of IAM actions and the resources they apply to. Use it through `cfn_typed.grants`."""

from dataclasses import dataclass
from typing import Literal

from cfn_typed.intrinsics import Expr, join
from cfn_typed.policy import Condition, Principal, Statement, allow

# Which resources a grant applies to, given the ARN you pass to `.on()`:
#   arn              the ARN itself (queue, topic, function, key, secret, ...)
#   arn_and_indexes  the ARN, and with `indexes=True` also `{arn}/index/*` (a DynamoDB table)
#   arn_and_objects  the ARN and the objects under it, `{arn}/{keys}` (an S3 bucket)
#   objects          only the objects under it
#   any              `*`, whatever ARN you have (so none is accepted)
Shape = Literal["arn", "arn_and_indexes", "arn_and_objects", "objects", "any"]

# For a resource policy (a grant with a principal), which `Resource` the statement gets:
#   arn   the resources the shape describes, from the ARN you pass (a bucket policy, a queue policy)
#   any   `"*"`: what a key policy needs, because the policy sits inside the key and cannot name its own ARN
#   omit  no `Resource` at all: what an ECR repository policy needs, where the field is not allowed
Target = Literal["arn", "any", "omit"]


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
        principal: Principal | None = None,
        condition: Condition | None = None,
        key_arn: Expr[str] | None = None,
        key_condition: Condition | None = None,
        keys: str | None = None,
        indexes: bool = False,
        target: Target = "arn",
    ) -> list[Statement]:
        """Statements that allow the actions on the resource.

        Without `principal` these are identity-policy statements (put them in a role or a managed policy); with
        one they are resource-policy statements (a bucket, queue or key policy) that name who is allowed.
        `condition` is added to that statement. `key_arn` adds a second statement for the KMS key actions, with
        `key_condition`; it is for identity policies only, since a resource policy cannot carry a statement about
        another resource, so for a key policy build it from `key_actions`.

        `keys` is the object key pattern for S3 grants (default `*`), `indexes=True` also covers a DynamoDB table's
        indexes, and `target` (resource policies only) picks the `Resource`: see `Target`.
        """
        if target != "arn" and principal is None:
            raise ValueError("`target` only applies to resource policies: pass a `principal`")
        if principal is not None and (key_arn is not None or key_condition is not None):
            raise ValueError("a resource policy cannot carry the key statement: build it for the key's own policy from `key_actions`")
        if key_condition is not None and key_arn is None:
            raise ValueError("`key_condition` needs `key_arn`")

        resources: list[Expr[str]] | Expr[str] | None
        if target != "arn":
            if arn is not None or keys is not None or indexes:
                raise ValueError(f"target={target!r} takes no ARN, `keys` or `indexes`")
            resources = "*" if target == "any" else None
        else:
            resources = self._resources(arn, keys, indexes)

        statements = [allow(list(self.actions), resources, principal=principal, condition=condition)]
        if self.key_actions and key_arn is not None:
            statements.append(allow(list(self.key_actions), key_arn, condition=key_condition))
        return statements

    def _resources(self, arn: Expr[str] | None, keys: str | None, indexes: bool) -> list[Expr[str]]:
        if self.shape == "any":
            if arn is not None:
                raise ValueError("this grant applies to '*', so it takes no ARN")
        elif arn is None:
            raise ValueError("this grant needs the ARN of the resource")
        if keys is not None and self.shape not in ("arn_and_objects", "objects"):
            raise ValueError("`keys` only applies to grants on objects, such as S3 buckets")
        if indexes and self.shape != "arn_and_indexes":
            raise ValueError("`indexes` only applies to DynamoDB table grants")

        if self.shape == "any" or arn is None:
            return ["*"]
        if self.shape == "arn":
            return [arn]
        if self.shape == "arn_and_indexes":
            return [arn, _child(arn, "index/*")] if indexes else [arn]
        if self.shape == "arn_and_objects":
            return [arn, _child(arn, keys or "*")]
        return [_child(arn, keys or "*")]  # objects
