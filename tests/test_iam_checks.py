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


def allow(action: Any, resource: Any = "*", condition: Any = None) -> dict[str, Any]:
    return {"Effect": "Allow", "Action": action, "Resource": resource} | ({} if condition is None else {"Condition": condition})


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


def test_good_conditions_are_quiet() -> None:
    like = {"StringLike": {"s3:prefix": ["clusters/abc/*"]}}
    t = template(
        allow("s3:ListBucket", "*", like),
        allow(["s3:ListBucket", "s3:GetObject"], "*", like),  # one action of the service takes the key
        allow("s3:*", "*", like), allow("*", "*", like), allow("s3:List*", "*", like),
        allow("s3:PutObject", "*", {"StringEquals": {"s3:x-amz-acl": "private"}, "ForAnyValue:StringLike": {"s3:RequestObjectTagKeys": "a*"}}),
        allow("s3:GetObject", "*", {"StringEquals": {"s3:ExistingObjectTag/Project": "x", "S3:ResourceAccount": "1"}}),  # `<key>` is any name; case does not matter
        allow("s3:GetObject", "*", {"StringEqualsIfExists": {"aws:PrincipalTag/team": "x"}, "Null": {"s3:authType": "false"}, "IpAddress": {"aws:SourceIp": "10.0.0.0/8"}}),
        allow("sqs:SendMessage", "*", {"ArnLikeIfExists": {"aws:SourceArn": "arn:*"}, "NumericLessThanEquals": {"s3:max-keys": 5}, "DateGreaterThan": {"aws:CurrentTime": "2030-01-01"}}),
        allow("ec2:DescribeInstances", "*", like),  # no s3 action in the statement: nothing to compare with
        {"Effect": "Deny", "NotAction": "s3:GetObject", "Resource": "*", "Condition": like},
        allow("s3:GetObject", "*", {"StringEquals": {"foo:Bar": "x"}}),  # a service without condition keys here is left alone
        allow(["s3:ListBucket"], "*", {"StringLike": {"s3:prefix": [sub("clusters/${AWS::Region}/*")]}}),
    )
    assert find_iam_problems(t) == []


def test_unknown_operators_effects_and_condition_keys() -> None:
    p = find_iam_problems(template(
        allow("s3:ListBucket", "*", {"StringLik": {"s3:prefix": "a"}, "ForAnyValue:StringEqualz": {"s3:prefix": "a"}, "NullIfExists": {"s3:prefix": "true"}}),
        allow("s3:ListBucket", "*", {"StringLike": {"s3:prefx": "a"}}),
        allow("sqs:SendMessage", "*", {"StringEquals": {"sqs:Anything": "a"}}),
        allow("kms:Decrypt", "*", {"StringEquals": {"kms:ViaServic": "s3.eu-west-1.amazonaws.com"}}),
        {"Effect": "Alow", "Action": "sqs:SendMessage", "Resource": "*"},
    ))
    base = "Resources.Policy.Properties.PolicyDocument.Statement"
    assert p == [
        f"{base}[0].Condition: 'StringLik' is not a condition operator (did you mean 'StringLike'?)",
        f"{base}[0].Condition: 'ForAnyValue:StringEqualz' is not a condition operator (did you mean 'StringEquals'?)",
        f"{base}[0].Condition: 'NullIfExists' is not a condition operator (did you mean 'Null'?)",
        f"{base}[1].Condition.StringLike: 's3:prefx' is not a known s3 condition key (did you mean 's3:prefix'?)",
        f"{base}[2].Condition.StringEquals: 'sqs:Anything' is not a known sqs condition key",
        f"{base}[3].Condition.StringEquals: 'kms:ViaServic' is not a known kms condition key (did you mean 'kms:ViaService'?)",
        f"{base}[4].Effect: 'Alow' is not 'Allow' or 'Deny'",
    ]


def test_a_condition_key_that_the_actions_do_not_take_is_reported() -> None:
    p = find_iam_problems(template(
        allow(["s3:GetObject", "s3:PutObject"], "*", {"StringLike": {"s3:prefix": "a/*"}}),
        allow("s3:Get*", "*", {"StringLike": {"S3:Delimiter": "/"}}),
    ))
    base = "Resources.Policy.Properties.PolicyDocument.Statement"
    assert len(p) == 2
    assert p[0].startswith(f"{base}[0].Condition.StringLike: 's3:prefix' is not a condition key of any s3 action in the statement; it is for s3:ListBucket")
    assert "'S3:Delimiter'" in p[1] and "s3:ListBucket" in p[1]
    with pytest.raises(AssertionError, match="IAM statements"):
        assert_iam_valid(template(allow("s3:GetObject", "*", {"StringLike": {"s3:prefix": "a"}})))
