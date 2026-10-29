from typing import Any, cast

import pytest

import cfn_typed as cfn
from cfn_typed import allow, deny, grants, policy_document
from cfn_typed.policy import (
    ANY, GlobalKeys, arn_like, aws, bool_, condition, ip_address, merge_conditions, service, string_equals, string_like,
)


def test_an_identity_statement_is_what_it_always_was() -> None:
    assert allow(["sqs:ReceiveMessage"], ["arn:q"]) == {"Effect": "Allow", "Action": ["sqs:ReceiveMessage"], "Resource": ["arn:q"]}
    assert allow("kms:*", "*") == {"Effect": "Allow", "Action": "kms:*", "Resource": "*"}  # a string action stays a string


def test_statements_keep_the_order_iam_documents() -> None:
    full = allow("s3:Get*", "arn:b", sid="X", principal=aws("arn:r"), condition=bool_("aws:SecureTransport", True))
    assert list(full) == ["Sid", "Effect", "Principal", "Action", "Resource", "Condition"]
    assert list(deny("s3:*", "arn:b")) == ["Effect", "Action", "Resource"]


def test_resource_can_be_left_out_and_deny_is_deny() -> None:
    statement = allow(["ecr:BatchGetImage"], principal=aws("arn:r"))
    assert "Resource" not in statement and statement["Effect"] == "Allow"
    assert deny("s3:*", "arn:b", principal=ANY)["Effect"] == "Deny"
    assert deny("s3:*", "arn:b", principal=ANY)["Principal"] == "*"


def test_principals_are_scalar_for_one_value_and_a_list_for_several() -> None:
    assert aws("arn:a") == {"AWS": "arn:a"}
    assert aws("arn:a", "arn:b") == {"AWS": ["arn:a", "arn:b"]}
    assert service("lambda.amazonaws.com") == {"Service": "lambda.amazonaws.com"}
    with pytest.raises(ValueError, match="at least one"):
        aws()


def test_conditions_normalise_booleans_and_numbers_and_keep_intrinsics() -> None:
    assert bool_("aws:SecureTransport", False) == {"Bool": {"aws:SecureTransport": "false"}}
    assert condition("NumericLessThan", "s3:max-keys", 10) == {"NumericLessThan": {"s3:max-keys": "10"}}
    ref = cfn.ref("Acct")
    assert string_equals(GlobalKeys.SourceAccount, ref) == {"StringEquals": {"aws:SourceAccount": ref}}
    assert string_like("aws:PrincipalArn", ["a*", ref]) == {"StringLike": {"aws:PrincipalArn": ["a*", ref]}}
    assert ip_address("aws:SourceIp", "10.0.0.0/8") == {"IpAddress": {"aws:SourceIp": "10.0.0.0/8"}}


def test_qualifiers_and_their_mistakes() -> None:
    assert string_equals("k", "v", for_any_value=True) == {"ForAnyValue:StringEquals": {"k": "v"}}
    assert string_equals("k", "v", for_all_values=True, if_exists=True) == {"ForAllValues:StringEqualsIfExists": {"k": "v"}}
    with pytest.raises(ValueError, match="ForAnyValue or ForAllValues"):
        condition("StringEquals", "k", "v", for_any_value=True, for_all_values=True)
    with pytest.raises(ValueError, match="IfExists"):
        condition("Null", "k", "true", if_exists=True)
    with pytest.raises(TypeError):
        condition("StringEquals", "k", cast(Any, [1.5]))  # a float is not a condition value


def test_merging_conditions() -> None:
    merged = merge_conditions(bool_("aws:SecureTransport", True), arn_like("aws:SourceArn", "arn:s"), string_equals("a", "1"), string_equals("b", "2"))
    assert merged == {"Bool": {"aws:SecureTransport": "true"}, "ArnLike": {"aws:SourceArn": "arn:s"}, "StringEquals": {"a": "1", "b": "2"}}
    with pytest.raises(ValueError, match="given twice"):
        merge_conditions(string_equals("a", "1"), string_equals("a", "2"))


def test_global_keys_are_the_iam_strings() -> None:
    assert GlobalKeys.SourceArn == "aws:SourceArn" and GlobalKeys.PrincipalArn == "aws:PrincipalArn"
    assert GlobalKeys.SecureTransport == "aws:SecureTransport"


def test_a_grant_with_a_principal_is_a_resource_policy_statement() -> None:
    who = aws("arn:aws:iam::111111111111:role/reader")
    [statement] = grants.S3.Bucket.read.on("arn:b", principal=who)
    assert statement["Principal"] == who and statement["Resource"] == ["arn:b", "arn:b/*"]
    assert statement["Action"] == ["s3:GetObject*", "s3:GetBucket*", "s3:List*"]
    narrowed = grants.Sqs.Queue.send_messages.on("arn:q", principal=service("sns.amazonaws.com"), condition=arn_like(GlobalKeys.SourceArn, "arn:topic"))
    assert narrowed[0]["Condition"] == {"ArnLike": {"aws:SourceArn": "arn:topic"}} and len(narrowed) == 1


def test_the_key_policy_and_repository_policy_shapes() -> None:
    [on_key] = grants.Kms.Key.decrypt.on(principal=aws("arn:r"), target="any")
    assert on_key["Resource"] == "*"  # inside a key policy: the key itself
    [on_repo] = grants.Kms.Key.decrypt.on(principal=aws("arn:r"), target="omit")
    assert "Resource" not in on_repo
    with pytest.raises(ValueError, match="takes no ARN"):
        grants.Kms.Key.decrypt.on("arn:k", principal=aws("arn:r"), target="any")
    with pytest.raises(ValueError, match="pass a `principal`"):
        grants.Kms.Key.decrypt.on(target="any")


def test_conditions_on_identity_grants_and_the_key_statement() -> None:
    statements = grants.S3.Bucket.read.on("arn:b", key_arn="arn:k", condition=bool_(GlobalKeys.SecureTransport, True),
                                          key_condition=string_equals("kms:ViaService", "s3.eu-north-1.amazonaws.com"))
    assert statements[0]["Condition"] == {"Bool": {"aws:SecureTransport": "true"}}
    assert statements[1]["Condition"] == {"StringEquals": {"kms:ViaService": "s3.eu-north-1.amazonaws.com"}}
    assert "Condition" not in grants.S3.Bucket.read.on("arn:b", key_arn="arn:k")[1]


def test_misuse_of_the_new_options_is_an_error() -> None:
    who = aws("arn:r")
    with pytest.raises(ValueError, match="cannot carry the key statement"):
        grants.S3.Bucket.read.on("arn:b", principal=who, key_arn="arn:k")
    with pytest.raises(ValueError, match="needs `key_arn`"):
        grants.S3.Bucket.read.on("arn:b", key_condition=bool_("k", True))


def test_a_resource_policy_goes_into_a_policy_document() -> None:
    document: Any = policy_document([
        deny("s3:*", "arn:b", sid="NoPlainHttp", principal=ANY, condition=bool_(GlobalKeys.SecureTransport, False)),
        *grants.S3.Bucket.read.on("arn:b", principal=aws("arn:r")),
    ])
    assert [s.get("Sid") for s in document["Statement"]] == ["NoPlainHttp", None]
    assert "Principal:" in cfn.to_yaml({"Resources": {}, "Mappings": {"P": dict(document)}})
