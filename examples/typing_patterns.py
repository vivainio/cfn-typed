"""Typing patterns shown in docs/typing-patterns.md; `ty check` covers this file like the rest of examples/."""

# --8<-- [start:optional]
from cfn_types import sqs


def jobs_queue(name: str, fifo: bool) -> sqs.Queue:
    props: sqs.QueueProps = {"QueueName": name}
    if fifo:
        props["FifoQueue"] = True
    return sqs.queue(**props)
# --8<-- [end:optional]


# --8<-- [start:fragment]
import cfn_typed as cfn
from cfn_typed import Expr
from cfn_types import s3


def lock_down() -> s3.BucketProps:
    """The properties every bucket here shares, as a typed fragment."""
    return {
        "PublicAccessBlockConfiguration": {
            "BlockPublicAcls": True, "BlockPublicPolicy": True, "IgnorePublicAcls": True, "RestrictPublicBuckets": True,
        },
    }


def audit_bucket(stage: Expr[str]) -> s3.Bucket:
    props = lock_down()
    props["Tags"] = [{"Key": "Stage", "Value": stage}]
    return s3.bucket(**props)
# --8<-- [end:fragment]
