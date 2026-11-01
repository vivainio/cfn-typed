"""A second made-up service with the usual events: a REST API, an HTTP API with a JWT authorizer, and an SQS consumer.

`build()` renders to exactly `original_api.json`, a template written in the style of `sls package`
(tests/test_serverless_eject_example.py). Nothing here is from a real account.
"""

# --8<-- [start:stack]
from cfn_typed_sumo import sls
from cfn_typed_sumo.types import sqs

import cfn_typed as cfn

SERVICE, STAGE = "shop", "dev"
S3_KEY = "serverless/shop/dev/1730000000000-2026-10-31T10:00:00.000Z/shop.zip"


def fn(key: str, version_id: str, **more):
    return sls.function(
        key, service=SERVICE, stage=STAGE, s3_key=S3_KEY, handler=f"{key}.handler", runtime="python3.12",
        memory=256, timeout=30, code_sha256="f" * 64, version_id=version_id, **more,
    )


def build() -> cfn.Template:
    todos, users = fn("todos", "TodosHash1"), fn("users", "UsersHash1")
    consumer = fn("consumer", "ConsumerHash1", log_destination="arn:aws:logs:eu-west-1:111111111111:destination:central")
    auth0 = sls.JwtAuthorizer("https://example.auth0.com/", ["https://api.example.com"])
    return {
        "AWSTemplateFormatVersion": "2010-09-09",
        "Description": "The AWS CloudFormation template for this Serverless application",
        "Resources": cfn.combine(
            sls.deployment_bucket(),
            sls.iam_role(SERVICE, STAGE, [
                cfn.allow(["dynamodb:GetItem", "dynamodb:PutItem"],
                          [cfn.sub("arn:${AWS::Partition}:dynamodb:${AWS::Region}:${AWS::AccountId}:table/shop-dev-todos")]),
                sls.sqs_statement("OrdersQueue"),
            ]),
            {"OrdersQueue": sqs.queue(QueueName="shop-dev-orders", VisibilityTimeout=60)},
            todos, users, consumer,
            sls.rest_api(SERVICE, STAGE, [
                sls.Route("/todos", "GET", "todos", private=True),
                sls.Route("/todos", "POST", "todos"),
                sls.Route("/todos/{id}", "GET", "todos"),
            ], deployment_id="1730000000001"),
            sls.http_api("dev-shop", [
                sls.HttpRoute("GET", "/users/{id}", "users", authorizer="auth0"),
                sls.HttpRoute("POST", "/users", "users", authorizer="auth0"),
            ], authorizers={"auth0": auth0}),
            sls.sqs_event("consumer", "OrdersQueue", batch_size=5),
        ),
        "Outputs": sls.outputs(SERVICE, STAGE, todos, users, consumer) | sls.endpoint_outputs(SERVICE, STAGE, rest=True, http=True),
    }
# --8<-- [end:stack]
