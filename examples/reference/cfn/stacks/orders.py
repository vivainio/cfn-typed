"""The orders stack: one queue with a dead-letter queue. The stage is a parameter, so one template serves every stage."""

# --8<-- [start:stack]
from dataclasses import dataclass
from pathlib import Path

import cfn_typed as cfn
from cfn_typed.cli import StackSpec
from patterns.queues import queue_with_dlq

HERE = Path(__file__).parent


@dataclass(frozen=True)
class OrdersConfig:
    visibility_timeout: int = 180


def build(config: OrdersConfig = OrdersConfig()) -> cfn.Template:
    params = cfn.Params()
    stage = params.string("Stage", default="dev", allowed_values=["dev", "test", "prod"])
    jobs = queue_with_dlq("Jobs", visibility_timeout=config.visibility_timeout, tags=[{"Key": "Stage", "Value": stage}])
    return {
        "AWSTemplateFormatVersion": "2010-09-09",
        "Parameters": params.declarations(),
        "Resources": jobs.resources,
        "Outputs": {"JobsUrl": {"Value": jobs.queue_url}, "JobsDlqUrl": {"Value": jobs.dlq_url}},
    }


def stacks() -> dict[str, StackSpec]:
    return {"orders": StackSpec(build, out=HERE.parent / "rendered")}
# --8<-- [end:stack]
