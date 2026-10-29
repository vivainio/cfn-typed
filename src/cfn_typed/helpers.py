"""Small hand-written helpers that need no generated types."""

from collections.abc import Mapping
from typing import Any, Literal, TypedDict

from cfn_typed.base import Tag
from cfn_typed.intrinsics import Expr

SQS_CONSUME = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
DDB_WRITE = ["dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem"]


def tags(**kv: str) -> list[Expr[Tag]]:
    return [{"Key": k, "Value": v} for k, v in kv.items()]


class Statement(TypedDict):
    Effect: Literal["Allow", "Deny"]
    Action: list[str]
    Resource: Expr[str] | list[Expr[str]]


def allow(actions: list[str], resource: Expr[str] | list[Expr[str]]) -> Statement:
    return {"Effect": "Allow", "Action": actions, "Resource": resource}


def merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    """Deep merge like Jsonnet's `+`: nested mappings merge key by key, anything else is replaced.

    `base | override` is shallow and would replace a whole `Environment`.
    """
    out = dict(base)
    for key, value in override.items():
        existing = out.get(key)
        out[key] = merge(existing, value) if isinstance(existing, Mapping) and isinstance(value, Mapping) else value
    return out
