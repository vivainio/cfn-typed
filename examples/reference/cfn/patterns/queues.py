"""A queue and its dead-letter queue, ejected from cfn_typed_sumo.patterns.

Copied as it was in sumo, with one change: the types come from this project's own generated `cfn_types`.
"""

from dataclasses import dataclass

from cfn_types import sqs

from cfn_typed import Expr, Resources, Tag, get_att, ref


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
