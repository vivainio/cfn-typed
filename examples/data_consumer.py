"""A stack that reads the storage published by data_platform.py, through SSM parameters."""

import cfn_typed as cfn
from cfn_types import iam
from cfn_typed import grants
from data_platform import PREFIX


# --8<-- [start:consumer]
def build() -> cfn.Template:
    params = cfn.Params()
    key_arn = params.ssm("DataKeyArn", f"{PREFIX}/key-arn")  # a Ref: the value is looked up at deploy time
    bucket_arn = params.ssm("DataBucketArn", f"{PREFIX}/bucket-arn")

    statements = grants.S3.Bucket.read.on(bucket_arn, key_arn=key_arn)

    return {
        "AWSTemplateFormatVersion": "2010-09-09",
        "Parameters": params.declarations(),
        "Resources": {
            "ReaderRole": iam.role(
                RoleName="data-platform-reader",  # matches the producer's allowed-principals pattern
                AssumeRolePolicyDocument={
                    "Version": "2012-10-17",
                    "Statement": [{
                        "Effect": "Allow",
                        "Principal": {"Service": ["lambda.amazonaws.com"]},
                        "Action": ["sts:AssumeRole"],
                    }],
                },
                Policies=[iam.RolePolicy(PolicyName="read-data", PolicyDocument=cfn.policy_document(statements))],
            ),
        },
    }
# --8<-- [end:consumer]


if __name__ == "__main__":
    print(cfn.to_yaml(build()))
