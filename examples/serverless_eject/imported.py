# Imported by `cfn-typed import`. Check it with `cfn-typed emit`, and compare it with the original template.

from cfn_types import events, iam, lambda_, logs, s3

import cfn_typed as cfn


def build() -> cfn.Template:
    return {
        "AWSTemplateFormatVersion": "2010-09-09",
        "Description": "The AWS CloudFormation template for this Serverless application",
        "Resources": {
            "ServerlessDeploymentBucket": s3.bucket(
                BucketEncryption={
                    "ServerSideEncryptionConfiguration": [
                        {
                            "ServerSideEncryptionByDefault": {
                                "SSEAlgorithm": "AES256",
                            },
                        },
                    ],
                },
            ),
            "ServerlessDeploymentBucketPolicy": s3.bucket_policy(
                Bucket=cfn.ref("ServerlessDeploymentBucket"),
                PolicyDocument={
                    "Statement": [
                        {
                            "Action": "s3:*",
                            "Effect": "Deny",
                            "Principal": "*",
                            "Resource": [
                                cfn.join("", [
                                    "arn:",
                                    cfn.ref("AWS::Partition"),
                                    ":s3:::",
                                    cfn.ref("ServerlessDeploymentBucket"),
                                    "/*",
                                ]),
                                cfn.join("", [
                                    "arn:",
                                    cfn.ref("AWS::Partition"),
                                    ":s3:::",
                                    cfn.ref("ServerlessDeploymentBucket"),
                                ]),
                            ],
                            "Condition": {
                                "Bool": {
                                    "aws:SecureTransport": False,
                                },
                            },
                        },
                    ],
                },
            ),
            "WorkerLogGroup": logs.log_group(
                LogGroupName="/aws/lambda/ledger-dev-worker",
                RetentionInDays=30,
            ),
            "IamRoleLambdaExecution": iam.role(
                AssumeRolePolicyDocument={
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Principal": {
                                "Service": ["lambda.amazonaws.com"],
                            },
                            "Action": ["sts:AssumeRole"],
                        },
                    ],
                },
                Policies=[
                    {
                        "PolicyName": cfn.join("-", ["ledger", "dev", "lambda"]),
                        "PolicyDocument": {
                            "Version": "2012-10-17",
                            "Statement": [
                                {
                                    "Effect": "Allow",
                                    "Action": ["logs:CreateLogStream", "logs:CreateLogGroup", "logs:TagResource"],
                                    "Resource": [
                                        cfn.sub("arn:${AWS::Partition}:logs:${AWS::Region}:${AWS::AccountId}:log-group:/aws/lambda/ledger-dev*:*"),
                                    ],
                                },
                                {
                                    "Effect": "Allow",
                                    "Action": ["logs:PutLogEvents"],
                                    "Resource": [
                                        cfn.sub("arn:${AWS::Partition}:logs:${AWS::Region}:${AWS::AccountId}:log-group:/aws/lambda/ledger-dev*:*:*"),
                                    ],
                                },
                            ],
                        },
                    },
                ],
                Path="/",
                RoleName=cfn.join("-", [
                    "ledger",
                    "dev",
                    cfn.ref("AWS::Region"),
                    "lambdaRole",
                ]),
            ),
            "WorkerLambdaFunction": lambda_.function(
                depends_on=["WorkerLogGroup"],
                Code={
                    "S3Bucket": cfn.ref("ServerlessDeploymentBucket"),
                    "S3Key": "serverless/ledger/dev/1730000000000-2026-10-31T10:00:00.000Z/ledger.zip",
                },
                Handler="handler.cleanup",
                Runtime="python3.12",
                FunctionName="ledger-dev-worker",
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
                Targets=[
                    {
                        "Arn": cfn.get_att("WorkerLambdaFunction", "Arn"),
                        "Id": "workerSchedule",
                    },
                ],
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
                "Export": {
                    "Name": "sls-ledger-dev-ServerlessDeploymentBucketName",
                },
            },
            "WorkerLambdaFunctionQualifiedArn": {
                "Description": "Current Lambda function version",
                "Value": cfn.ref("WorkerLambdaVersionAbc123def456"),
                "Export": {
                    "Name": "sls-ledger-dev-WorkerLambdaFunctionQualifiedArn",
                },
            },
        },
    }
