"""Pattern helpers shown in the book (docs/). Sections feed the pages via pymdownx.snippets."""

# --8<-- [start:imports]
from collections.abc import Sequence
from dataclasses import dataclass

from cfn_types import iam, lambda_, sqs

from cfn_typed import AnyStatement, Expr, Resources, Tag, allow, arn, assume_role_policy, get_att, policy_document, ref
from cfn_typed.policy import service

# --8<-- [end:imports]


# --8<-- [start:lambda_role]
def lambda_role(name_prefix: str, extra: Sequence[AnyStatement]) -> iam.Role:
    """Execution role for a Lambda: log permissions plus the `extra` statements."""
    log_arn = arn("logs", f"log-group:/aws/lambda/{name_prefix}*:*")
    return iam.role(
        AssumeRolePolicyDocument=assume_role_policy(service("lambda.amazonaws.com")),
        Policies=[iam.RolePolicy(
            PolicyName=f"{name_prefix}-lambda",
            PolicyDocument=policy_document([
                allow(["logs:CreateLogStream", "logs:CreateLogGroup", "logs:PutLogEvents"], [log_arn]),
                *extra,
            ]),
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
@dataclass(frozen=True)
class QueueWithDlq:
    """The handle `queue_with_dlq` returns: the logical IDs, how to refer to them, and the resources."""

    queue: str
    dlq: str
    resources: Resources

    @property
    def queue_arn(self) -> Expr[str]:
        return get_att(self.queue, "Arn")

    @property
    def queue_url(self) -> Expr[str]:
        return ref(self.queue)

    @property
    def dlq_url(self) -> Expr[str]:
        return ref(self.dlq)


def queue_with_dlq(
    name: str,
    *,
    visibility_timeout: int = 30,
    max_receive_count: int = 3,
    tags: list[Expr[Tag]] | None = None,
) -> QueueWithDlq:
    """A queue and its dead-letter queue, with logical IDs `{name}Queue` and `{name}DLQ`."""
    queue_id, dlq_id = f"{name}Queue", f"{name}DLQ"
    dlq: sqs.QueueProps = {}
    main: sqs.QueueProps = {
        "VisibilityTimeout": visibility_timeout,
        "RedrivePolicy": {"deadLetterTargetArn": get_att(dlq_id, "Arn"), "maxReceiveCount": max_receive_count},
    }
    if tags:
        dlq["Tags"] = main["Tags"] = tags
    return QueueWithDlq(queue_id, dlq_id, {dlq_id: sqs.queue(**dlq), queue_id: sqs.queue(**main)})


# --8<-- [end:queue_with_dlq]
