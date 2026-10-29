"""Small hand-written helpers that need no generated types."""

from typing import Any

from cfn_typed.base import Tag
from cfn_typed.intrinsics import Expr

SQS_CONSUME = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
DDB_WRITE = ["dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem"]


def tags(**kv: str) -> list[Expr[Tag]]:
    return [{"Key": k, "Value": v} for k, v in kv.items()]


def allow(actions: list[str], resource: Expr[str] | list[Expr[str]]) -> dict[str, Any]:
    return {"Effect": "Allow", "Action": actions, "Resource": resource}
