"""A stack that owns encrypted storage and publishes where it is, for other stacks to read."""

import cfn_typed as cfn
from cfn_typed import Expr, Tag, get_att, sub
from storage import dynamodb_table, encryption_key, publish, secure_bucket

PREFIX = "/data-platform/storage"


# --8<-- [start:producer]
def build() -> cfn.Template:
    params = cfn.Params()
    stage = params.string("Stage", default="dev", allowed_values=["dev", "test", "prod"])
    deploy_role = params.string("DeployRoleArn", description="The role that deploys this stack: it must keep bucket access")
    tags: list[Expr[Tag]] = [{"Key": "Stage", "Value": stage}]

    return {
        "AWSTemplateFormatVersion": "2010-09-09",
        "Parameters": params.declarations(),
        "Resources": cfn.combine(
            encryption_key("Data", alias="data-platform", tags=tags),
            secure_bucket(
                "Data",
                key_arn=get_att("DataKey", "Arn"),
                allowed_principals=[deploy_role, sub("arn:${AWS::Partition}:iam::${AWS::AccountId}:role/data-platform-*")],
                archive_after_days=90,
                tags=tags,
            ),
            {
                "EventsTable": dynamodb_table("pk", "sk", tags=tags),
                "ConfigTable": dynamodb_table("id", tags=tags),
            },
            publish(PREFIX, {"key-arn": get_att("DataKey", "Arn"), "bucket-arn": get_att("DataBucket", "Arn")}),
        ),
    }
# --8<-- [end:producer]


if __name__ == "__main__":
    print(cfn.to_yaml(build()))
