"""One stack per bucket, all from the same function: a config object and a StackSpec for each."""

# --8<-- [start:stack]
from dataclasses import dataclass
from functools import partial
from pathlib import Path

import cfn_typed as cfn
from cfn_types import s3
from cfn_typed.cli import StackSpec

HERE = Path(__file__).parent


@dataclass(frozen=True)
class BucketConfig:
    name: str                                # also the stack name: bucket-<name>
    data_class: str                          # a tag value: audit, customer-data, ...
    archive_after_days: int | None = None


def build(config: BucketConfig) -> cfn.Template:
    props: s3.BucketProps = {
        "PublicAccessBlockConfiguration": {
            "BlockPublicAcls": True, "BlockPublicPolicy": True, "IgnorePublicAcls": True, "RestrictPublicBuckets": True,
        },
        "BucketEncryption": {"ServerSideEncryptionConfiguration": [
            {"ServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}},
        ]},
        "Tags": cfn.tags(DataClass=config.data_class),
    }
    if config.archive_after_days is not None:
        props["LifecycleConfiguration"] = {"Rules": [{
            "Id": "archive", "Status": "Enabled",
            "Transitions": [{"StorageClass": "GLACIER", "TransitionInDays": config.archive_after_days}],
        }]}
    return {
        "AWSTemplateFormatVersion": "2010-09-09",
        "Resources": {"Bucket": s3.bucket(deletion_policy="Retain", update_replace_policy="Retain", **props)},
        "Outputs": {"BucketName": {"Value": cfn.ref("Bucket")}},
    }


CONFIGS = [
    BucketConfig("logs", "audit", archive_after_days=90),
    BucketConfig("uploads", "customer-data"),
    BucketConfig("exports", "customer-data"),
]


def stacks() -> dict[str, StackSpec]:
    return {
        f"bucket-{c.name}": StackSpec(partial(build, c), out=HERE.parent / "rendered/buckets")
        for c in CONFIGS
    }
# --8<-- [end:stack]
