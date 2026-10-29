"""Helper functions that create common resources, or small fragments of several.

Fragments are plain `Resources` dicts; combine them with `|`. Logical IDs follow a
documented convention (`queue_with_dlq("Order")` -> `OrderQueue`, `OrderDLQ`), so
callers can refer to them with `ref` / `get_att`.

The resources are built with a small private set of generated types (`_gen`) and
returned as `AnyResource`, so they mix freely with types you generate yourself.
"""

from cfn_typed._gen import iam, lambda_, sqs
from cfn_typed.base import AnyResource, Resources, Tag
from cfn_typed.helpers import Statement, allow
from cfn_typed.intrinsics import Expr, arn, get_att


def lambda_role(name_prefix: str, extra: list[Statement]) -> AnyResource:
    """Execution role for a Lambda: log permissions plus the `extra` statements."""
    log_arn = arn("logs", f"log-group:/aws/lambda/{name_prefix}*:*")
    return iam.role(
        AssumeRolePolicyDocument={
            "Version": "2012-10-17",
            "Statement": [{
                "Effect": "Allow",
                "Principal": {"Service": ["lambda.amazonaws.com"]},
                "Action": ["sts:AssumeRole"],
            }],
        },
        Policies=[iam.RolePolicy(
            PolicyName=f"{name_prefix}-lambda",
            PolicyDocument={
                "Version": "2012-10-17",
                "Statement": [
                    allow(["logs:CreateLogStream", "logs:CreateLogGroup", "logs:PutLogEvents"], [log_arn]),
                    *extra,
                ],
            },
        )],
    )


def sqs_event_source(function_logical: str, queue_arn: Expr[str], batch_size: int = 10) -> AnyResource:
    """Trigger the Lambda `function_logical` from an SQS queue."""
    return lambda_.event_source_mapping(
        BatchSize=batch_size,
        EventSourceArn=queue_arn,
        FunctionName=get_att(function_logical, "Arn"),
    )


def queue_with_dlq(
    name: str,
    *,
    visibility_timeout: int = 30,
    max_receive_count: int = 3,
    tags: list[Expr[Tag]] | None = None,
) -> Resources:
    """A queue and its dead-letter queue: logical IDs `{name}Queue` and `{name}DLQ`."""
    dlq: sqs.QueueProps = {}
    main: sqs.QueueProps = {
        "VisibilityTimeout": visibility_timeout,
        "RedrivePolicy": {"deadLetterTargetArn": get_att(f"{name}DLQ", "Arn"), "maxReceiveCount": max_receive_count},
    }
    if tags:
        dlq["Tags"] = main["Tags"] = tags
    return {f"{name}DLQ": sqs.queue(**dlq), f"{name}Queue": sqs.queue(**main)}
