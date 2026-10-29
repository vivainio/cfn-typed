"""Every intrinsic function and condition function in one small template. Shown in the book (docs/intrinsics.md)."""

import cfn_typed as cfn
from cfn_types import ec2, sqs, ssm

from cfn_typed import (
    and_, base64, cidr, condition_ref, equals, find_in_map, get_att, get_azs, if_, import_value, join, not_, ref, select,
    split, sub,
)


# --8<-- [start:demo]
def build() -> cfn.Template:
    params = cfn.Params()
    stage = params.string("Stage", default="dev", allowed_values=["dev", "prod"])
    network = params.string("NetworkStack", default="network", description="The stack that exports the VPC")
    attribute = params.string("QueueAttribute", default="Arn", allowed_values=["Arn", "QueueName"])

    return {
        "AWSTemplateFormatVersion": "2010-09-09",
        "Parameters": params.declarations(),
        "Mappings": {"Sizes": {"dev": {"Timeout": "30"}, "prod": {"Timeout": "120"}}},
        "Conditions": {
            "IsProd": equals(stage, "prod"),
            "IsNorthEurope": equals(ref("AWS::Region"), "eu-north-1"),
            "ProdInNorthEurope": and_(condition_ref("IsProd"), condition_ref("IsNorthEurope")),
            "NotProd": not_(condition_ref("IsProd")),
        },
        "Resources": {
            "Queue": sqs.queue(
                QueueName=sub("${Prefix}-${Stage}", {"Prefix": "orders"}),            # Fn::Sub with variables
                VisibilityTimeout=find_in_map("Sizes", stage, "Timeout"),             # Fn::FindInMap
                DelaySeconds=if_("IsProd", 5, ref("AWS::NoValue")),                   # Fn::If, leaving a property out
            ),
            "QueueUrl": ssm.parameter(
                Type="String",
                Name=join("/", ["", "orders", stage, "queue-url"]),                   # Fn::Join
                Value=ref("Queue"),                                                   # Ref
            ),
            "QueueDetail": ssm.parameter(
                Type="String", Name="/orders/detail",
                Value=get_att("Queue", attribute),                                    # Fn::GetAtt, with a Ref as the attribute
            ),
            "FirstZone": ssm.parameter(Type="String", Name="/orders/first-zone", Value=select(0, get_azs())),  # Fn::Select, Fn::GetAZs
            "SecondItem": ssm.parameter(Type="String", Name="/orders/second", Value=select(1, split(",", "a,b,c"))),  # Fn::Split
            "Bootstrap": ssm.parameter(Type="String", Name="/orders/bootstrap", Value=base64(sub("echo ${Stage}"))),  # Fn::Base64
            "ProdOnly": ssm.parameter(Type="String", Name="/orders/prod-only", Value="yes", condition="ProdInNorthEurope"),
            "Group": ec2.security_group(
                GroupDescription="orders",
                VpcId=import_value(sub("${NetworkStack}-VpcId")),                     # Fn::ImportValue
                SecurityGroupIngress=[{
                    "IpProtocol": "tcp", "FromPort": 443, "ToPort": 443,
                    "CidrIp": select(0, cidr("10.0.0.0/16", 4, 8)),                   # Fn::Cidr
                }],
            ),
        },
    }
# --8<-- [end:demo]


if __name__ == "__main__":
    print(cfn.to_yaml(build()))
