"""Reusable patterns built on generated factories (regenerate cfn_types with cfn-typegen)."""

from cfn_types import iam, lambda_
from cfn_typed import Expr, Statement, allow, arn, get_att


def lambda_role(name_prefix: str, extra: list[Statement]) -> iam.Role:
    log_arn = arn("logs", f"log-group:/aws/lambda/{name_prefix}*:*")
    return iam.role(
        AssumeRolePolicyDocument={
            "Version": "2012-10-17",
            "Statement": [{
                "Effect": "Allow",
                "Principal": {"Service": ["lambda.amazonaws.com"]},
                "Action": ["sts:AssumeRole"],
            }],
        },
        Policies=[iam.RolePolicy(
            PolicyName=f"{name_prefix}-lambda",
            PolicyDocument={
                "Version": "2012-10-17",
                "Statement": [
                    allow(["logs:CreateLogStream", "logs:CreateLogGroup", "logs:PutLogEvents"], [log_arn]),
                    *extra,
                ],
            },
        )],
    )


def sqs_event_source(function_logical: str, queue_arn: Expr[str], batch_size: int = 10) -> lambda_.EventSourceMapping:
    return lambda_.event_source_mapping(
        BatchSize=batch_size,
        EventSourceArn=queue_arn,
        FunctionName=get_att(function_logical, "Arn"),
    )
