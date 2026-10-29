"""SQS consumer with a dead-letter queue — the Python twin of sqs-worker.jsonnet."""

import json
import sys

import cfn_typed as cfn
from cfn_typed import grants
from cfn_types import lambda_
from patterns import lambda_role, queue_with_dlq, sqs_event_source

service = "order-processor"
stage = sys.argv[1] if len(sys.argv) > 1 else "dev"

t = cfn.tags(Service=service, Stage=stage)

# --8<-- [start:stack]
orders = queue_with_dlq("Order", visibility_timeout=180, tags=t)

resources = cfn.combine(
    {
        "ExecutionRole": lambda_role(f"{service}-{stage}", [
            *grants.Sqs.Queue.consume_messages.on(orders.queue_arn),
            *grants.DynamoDb.Table.write_data.on(cfn.arn("dynamodb", f"table/orders-{stage}")),
        ]),
        "Processor": lambda_.function(
            FunctionName=f"{service}-{stage}-processor",
            Handler="src/processor.handler",
            Runtime="nodejs20.x",
            Role=cfn.get_att("ExecutionRole", "Arn"),
            Code=lambda_.FunctionCode(S3Bucket="deploy-artifacts", S3Key=f"{service}/{stage}/package.zip"),
            MemorySize=256,
            Timeout=30,
            Environment=lambda_.FunctionEnvironment(Variables={"STAGE": stage, "TABLE_NAME": f"orders-{stage}"}),
            ReservedConcurrentExecutions=5,
            Tags=t,
        ),
        "ProcessorEventSourceMapping": sqs_event_source("Processor", orders.queue_arn),
    },
    orders,
)

template: cfn.Template = {
    "AWSTemplateFormatVersion": "2010-09-09",
    "Resources": resources,
    "Outputs": {
        "QueueUrl": {"Value": orders.queue_url},
        "DLQUrl": {"Value": orders.dlq_url},
    },
}
# --8<-- [end:stack]

print(json.dumps(template, indent=2))
