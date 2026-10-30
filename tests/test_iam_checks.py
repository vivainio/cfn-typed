from typing import Any

import pytest

from cfn_typed import get_att, join, ref, sub
from cfn_typed.iam import KNOWN, find_iam_problems
from cfn_typed.testing import assert_iam_valid


def template(*statements: dict[str, Any]) -> dict[str, Any]:
    return {"Resources": {
        "Queue": {"Type": "AWS::SQS::Queue"}, "Topic": {"Type": "AWS::SNS::Topic"}, "Bucket": {"Type": "AWS::S3::Bucket"}, "Role": {"Type": "AWS::IAM::Role"},
        "Policy": {"Type": "AWS::IAM::Policy", "Properties": {"PolicyDocument": {"Version": "2012-10-17", "Statement": list(statements)}}},
    }}


def allow(action: Any, resource: Any = "*") -> dict[str, Any]:
    return {"Effect": "Allow", "Action": action, "Resource": resource}


def test_the_known_actions_are_read_from_permissions() -> None:
    assert {"sqs", "s3", "kms", "dynamodb", "secretsmanager"} <= set(KNOWN) and "ReceiveMessage" in KNOWN["sqs"]


def test_good_statements_are_quiet() -> None:
    t = template(
        allow(["sqs:ReceiveMessage", "SQS:deletemessage"], get_att("Queue", "Arn")),
        allow("sqs:*", "*"), allow("sts:AssumeRole", get_att("Role", "Arn")), allow("ec2:Whatever"), allow("s3:Get*", get_att("Bucket", "Arn")),
        allow(["s3:GetObject", "s3:PutObject"], sub("${Bucket.Arn}/*")), allow("s3:ListBucket", get_att("Bucket", "Arn")),
        allow(["s3:GetObject", "s3:ListBucket"], [get_att("Bucket", "Arn"), join("", [get_att("Bucket", "Arn"), "/*"])]),
        allow(["sqs:SendMessage", "kms:Decrypt"], [get_att("Queue", "Arn"), "*"]),
    )
    assert find_iam_problems(t) == []
    assert_iam_valid(t)


def test_unknown_actions_and_empty_wildcards() -> None:
    p = find_iam_problems(template(allow(["sqs:ReceiveMesage", "sqs:Nope*", "sqs:Receive*", "bogus:Anything"])))
    assert p == [
        "Resources.Policy.Properties.PolicyDocument.Statement[0].Action: 'sqs:ReceiveMesage' is not a known sqs action (did you mean 'sqs:ReceiveMessage'?)",
        "Resources.Policy.Properties.PolicyDocument.Statement[0].Action: 'sqs:Nope*' matches no sqs action",
    ]


def test_a_resource_of_another_service_is_reported() -> None:
    p = find_iam_problems(template(allow("sqs:SendMessage", get_att("Topic", "TopicArn")), allow(["sns:Publish", "sqs:SendMessage"], [ref("Topic"), sub("${Queue.Arn}")])))
    assert len(p) == 1 and "refers to 'Topic' (AWS::SNS::Topic), but no action in the statement is a sns action" in p[0]


def test_s3_object_and_bucket_arns_are_told_apart() -> None:
    p = find_iam_problems(template(
        allow("s3:GetObject", get_att("Bucket", "Arn")), allow("s3:ListBucket", join("", [get_att("Bucket", "Arn"), "/*"])),
        allow("s3:GetObject", "arn:aws:s3:::fixed"), allow("s3:ListBucket", "arn:aws:s3:::fixed/*"), allow("s3:GetObject", sub("${Bucket.Arn}")),
    ))
    assert len(p) == 5
    assert "'GetObject' applies to objects, but Resource is only the bucket ARN" in p[0] and "'ListBucket' applies to the bucket" in p[1]
    with pytest.raises(AssertionError, match="IAM statements"):
        assert_iam_valid(template(allow("s3:GetObject", get_att("Bucket", "Arn"))))


def test_resource_policies_and_single_statements_are_read_too() -> None:
    t = {"Resources": {"Queue": {"Type": "AWS::SQS::Queue"}, "QP": {"Type": "AWS::SQS::QueuePolicy", "Properties": {"PolicyDocument": {"Statement": allow("sqs:SendMesage")}}}}}
    assert len(find_iam_problems(t)) == 1
