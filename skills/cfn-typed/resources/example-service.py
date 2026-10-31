"""A small service from the core constructs: queue + dead-letter queue, a function with its role and logs,
an SQS trigger, a schedule, a table and an alarm. Type-checks with `ty` and renders with cfn.to_yaml(build())."""

import cfn_typed as cfn
from cfn_typed import grants
from cfn_typed_sumo import queue_with_dlq, sqs_event_source
from cfn_typed_sumo.constructs import function, lambda_errors_alarm, schedule
from cfn_typed_sumo.storage import dynamodb_table
from cfn_typed_sumo.types import lambda_


def build() -> cfn.Template:
    orders = queue_with_dlq("Orders", visibility_timeout=180)
    worker = function(
        "Worker",
        code=lambda_.FunctionCode(S3Bucket="deploy-artifacts", S3Key="orders/package.zip"),
        handler="handler.process",
        runtime="python3.12",
        memory=512,
        timeout=60,
        environment={"TABLE": cfn.ref("Table")},
        statements=[
            *grants.Sqs.Queue.consume_messages.on(orders.queue_arn),
            cfn.allow("dynamodb:PutItem", cfn.get_att("Table", "Arn")),
        ],
    )
    return {
        "AWSTemplateFormatVersion": "2010-09-09",
        "Resources": cfn.combine(
            orders,
            worker,
            {"Table": dynamodb_table("pk", "sk")},
            {"OrdersTrigger": sqs_event_source(worker.function, orders.queue_arn)},
            schedule("Nightly", "cron(0 3 * * ? *)", worker.function),
            {"WorkerErrors": lambda_errors_alarm(worker.function)},
        ),
    }
