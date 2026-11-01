"""SQS consumer with a dead-letter queue — the Python twin of sqs-worker.jsonnet."""

import json
from dataclasses import dataclass

import cfn_typed as cfn
from cfn_typed import grants
from cfn_types import lambda_
from cfn_typed_sumo.patterns import lambda_role, queue_with_dlq, sqs_event_source


# --8<-- [start:stack]
@dataclass(frozen=True)
class WorkerConfig:
    service: str = "order-processor"
    table: str = "orders"                  # the table's name is <table>-<Stage>
    memory: int = 256
    concurrency: int = 5


def build(config: WorkerConfig = WorkerConfig()) -> cfn.Template:
    params = cfn.Params()
    stage = params.string("Stage", default="dev", allowed_values=["dev", "test", "prod"])
    tags: list[cfn.Expr[cfn.Tag]] = [{"Key": "Service", "Value": config.service}, {"Key": "Stage", "Value": stage}]
    table = f"{config.table}-${{Stage}}"          # ${Stage} is resolved by CloudFormation, in Sub

    orders = queue_with_dlq("Order", visibility_timeout=180, tags=tags)

    return {
        "AWSTemplateFormatVersion": "2010-09-09",
        "Parameters": params.declarations(),
        "Resources": cfn.combine(
            {
                "ExecutionRole": lambda_role(config.service, [
                    *grants.Sqs.Queue.consume_messages.on(orders.queue_arn),
                    *grants.DynamoDb.Table.write_data.on(cfn.arn.table(table)),
                ]),
                "Processor": lambda_.function(
                    FunctionName=cfn.sub(f"{config.service}-${{Stage}}-processor"),
                    Handler="src/processor.handler",
                    Runtime="nodejs20.x",
                    Role=cfn.get_att("ExecutionRole", "Arn"),
                    Code=lambda_.FunctionCode(S3Bucket="deploy-artifacts", S3Key=cfn.sub(f"{config.service}/${{Stage}}/package.zip")),
                    MemorySize=config.memory,
                    Timeout=30,
                    Environment=lambda_.FunctionEnvironment(Variables={"STAGE": stage, "TABLE_NAME": cfn.sub(table)}),
                    ReservedConcurrentExecutions=config.concurrency,
                    Tags=tags,
                ),
                "ProcessorEventSourceMapping": sqs_event_source("Processor", orders.queue_arn),
            },
            orders,
        ),
        "Outputs": {
            "QueueUrl": {"Value": orders.queue_url},
            "DLQUrl": {"Value": orders.dlq_url},
        },
    }
# --8<-- [end:stack]


if __name__ == "__main__":
    print(json.dumps(build(), indent=2))
