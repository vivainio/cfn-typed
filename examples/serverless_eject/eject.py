"""A made-up Serverless Framework service, ejected (see docs/patterns/eject-serverless.md).

`original.json` is what `sls package` wrote. `imported.py` is `cfn-typed import` run on it: it renders back to exactly
the original. This module is the same stack after a hand pass: the service name and stage are two values instead of
being repeated in strings, the repeated ARN is built once, and each resource keeps the logical ID the framework
gave it, so CloudFormation sees the same stack. Nothing in these files is from a real account.
"""

from cfn_types import events, iam, lambda_, logs, s3

import cfn_typed as cfn

# --8<-- [start:names]
SERVICE, STAGE = "ledger", "dev"
PREFIX = f"{SERVICE}-{STAGE}"
LOG_GROUPS = f"arn:${{AWS::Partition}}:logs:${{AWS::Region}}:${{AWS::AccountId}}:log-group:/aws/lambda/{PREFIX}*:*"
# --8<-- [end:names]


def bucket_arn(suffix: str = "") -> cfn.Expr[str]:
    return cfn.join("", ["arn:", cfn.ref("AWS::Partition"), ":s3:::", cfn.ref("ServerlessDeploymentBucket"), *([suffix] if suffix else [])])


def build() -> cfn.Template:
    # --8<-- [start:resources]
    return {
        "AWSTemplateFormatVersion": "2010-09-09",
        "Description": "The AWS CloudFormation template for this Serverless application",
        "Resources": {
            "ServerlessDeploymentBucket": s3.bucket(
                BucketEncryption={"ServerSideEncryptionConfiguration": [{"ServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]},
            ),
            "ServerlessDeploymentBucketPolicy": s3.bucket_policy(
                Bucket=cfn.ref("ServerlessDeploymentBucket"),
                PolicyDocument={
                    "Statement": [{
                        "Action": "s3:*",
                        "Effect": "Deny",
                        "Principal": "*",
                        "Resource": [bucket_arn("/*"), bucket_arn()],
                        "Condition": {"Bool": {"aws:SecureTransport": False}},
                    }],
                },
            ),
            "WorkerLogGroup": logs.log_group(LogGroupName=f"/aws/lambda/{PREFIX}-worker", RetentionInDays=30),
            "IamRoleLambdaExecution": iam.role(
                AssumeRolePolicyDocument={
                    "Version": "2012-10-17",
                    "Statement": [{"Effect": "Allow", "Principal": {"Service": ["lambda.amazonaws.com"]}, "Action": ["sts:AssumeRole"]}],
                },
                Policies=[{
                    "PolicyName": cfn.join("-", [SERVICE, STAGE, "lambda"]),
                    "PolicyDocument": {
                        "Version": "2012-10-17",
                        "Statement": [
                            {"Effect": "Allow", "Action": ["logs:CreateLogStream", "logs:CreateLogGroup", "logs:TagResource"], "Resource": [cfn.sub(LOG_GROUPS)]},
                            {"Effect": "Allow", "Action": ["logs:PutLogEvents"], "Resource": [cfn.sub(LOG_GROUPS + ":*")]},
                        ],
                    },
                }],
                Path="/",
                RoleName=cfn.join("-", [SERVICE, STAGE, cfn.ref("AWS::Region"), "lambdaRole"]),
            ),
            "WorkerLambdaFunction": lambda_.function(
                depends_on=["WorkerLogGroup"],
                Code={
                    "S3Bucket": cfn.ref("ServerlessDeploymentBucket"),
                    "S3Key": "serverless/ledger/dev/1730000000000-2026-10-31T10:00:00.000Z/ledger.zip",
                },
                Handler="handler.cleanup",
                Runtime="python3.12",
                FunctionName=f"{PREFIX}-worker",
                MemorySize=512,
                Timeout=600,
                Role=cfn.get_att("IamRoleLambdaExecution", "Arn"),
            ),
            "WorkerLambdaVersionAbc123def456": lambda_.version(
                deletion_policy="Retain",
                FunctionName=cfn.ref("WorkerLambdaFunction"),
                CodeSha256="abc123def456abc123def456abc123def456abc123def456abc123def456abcd",
            ),
            "WorkerEventsRuleSchedule1": events.rule(
                ScheduleExpression="cron(0 3 * * ? *)",
                State="ENABLED",
                Targets=[{"Arn": cfn.get_att("WorkerLambdaFunction", "Arn"), "Id": "workerSchedule"}],
            ),
            "WorkerLambdaPermissionEventsRuleSchedule1": lambda_.permission(
                FunctionName=cfn.get_att("WorkerLambdaFunction", "Arn"),
                Action="lambda:InvokeFunction",
                Principal="events.amazonaws.com",
                SourceArn=cfn.get_att("WorkerEventsRuleSchedule1", "Arn"),
            ),
        },
        "Outputs": {
            "ServerlessDeploymentBucketName": {
                "Value": cfn.ref("ServerlessDeploymentBucket"),
                "Export": {"Name": f"sls-{PREFIX}-ServerlessDeploymentBucketName"},
            },
            "WorkerLambdaFunctionQualifiedArn": {
                "Description": "Current Lambda function version",
                "Value": cfn.ref("WorkerLambdaVersionAbc123def456"),
                "Export": {"Name": f"sls-{PREFIX}-WorkerLambdaFunctionQualifiedArn"},
            },
        },
    }
    # --8<-- [end:resources]
