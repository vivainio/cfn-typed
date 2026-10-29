"""Pattern helpers shown in the book (docs/). Sections feed the pages via pymdownx.snippets."""

# --8<-- [start:imports]
from cfn_types import iam, lambda_, sqs

from cfn_typed import AnyResource, Expr, Resources, Statement, Tag, allow, arn, get_att

# --8<-- [end:imports]


# --8<-- [start:lambda_role]
def lambda_role(name_prefix: str, extra: list[Statement]) -> iam.Role:
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
# --8<-- [end:lambda_role]


# --8<-- [start:sqs_event_source]
def sqs_event_source(function_logical: str, queue_arn: Expr[str], batch_size: int = 10) -> lambda_.EventSourceMapping:
    """Trigger the Lambda `function_logical` from an SQS queue."""
    return lambda_.event_source_mapping(
        BatchSize=batch_size,
        EventSourceArn=queue_arn,
        FunctionName=get_att(function_logical, "Arn"),
    )
# --8<-- [end:sqs_event_source]


# --8<-- [start:queue_with_dlq]
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
# --8<-- [end:queue_with_dlq]


# --8<-- [start:combine]
def combine(*fragments: Resources) -> Resources:
    """Merge fragments like `|`, but refuse to silently overwrite a logical ID."""
    out: dict[str, AnyResource] = {}
    for fragment in fragments:
        clash = out.keys() & fragment.keys()
        if clash:
            raise ValueError(f"duplicate logical IDs: {', '.join(sorted(clash))}")
        out |= fragment
    return out
# --8<-- [end:combine]
