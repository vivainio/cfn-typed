"""The Serverless Framework `functions:` example from the book (docs/patterns/serverless.md)."""

# --8<-- [start:stack]
import cfn_typed as cfn
from cfn_types import lambda_
from cfn_typed_sumo.constructs import function, schedule


def build() -> cfn.Template:
    worker = function(
        "Worker",
        code=lambda_.FunctionCode(S3Bucket="deploy-artifacts", S3Key="my-service/package.zip"),
        handler="handler.cleanup",
        runtime="python3.12",
        memory=512,
        timeout=600,
    )
    return {
        "AWSTemplateFormatVersion": "2010-09-09",
        "Resources": cfn.combine(worker, schedule("Worker", "cron(0 3 * * ? *)", worker.function)),
    }
# --8<-- [end:stack]
