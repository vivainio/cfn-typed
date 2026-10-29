import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent / "examples"))

import data_consumer  # noqa: E402
import data_platform  # noqa: E402
from storage import dynamodb_table, ecr_repository, encryption_key, publish, secure_bucket  # noqa: E402

import cfn_typed as cfn  # noqa: E402


def plain(value: Any) -> Any:
    """What CloudFormation would see: tests inspect the rendered JSON, not the typed structure."""
    return json.loads(json.dumps(value))


def refs(node: Any) -> set[str]:
    if isinstance(node, dict):
        found = {node["Ref"]} if set(node) == {"Ref"} else set()
        return found.union(*(refs(v) for v in node.values()))
    if isinstance(node, list):
        return set().union(*(refs(v) for v in node))
    return set()


def test_the_key_keeps_its_policy_self_contained_and_is_retained() -> None:
    frag = plain(encryption_key("Data", alias="platform"))
    assert set(frag) == {"DataKey", "DataKeyAlias"}
    key = frag["DataKey"]
    assert key["DeletionPolicy"] == "Retain" and key["UpdateReplacePolicy"] == "Retain"
    assert key["Properties"]["EnableKeyRotation"] is True
    statement = key["Properties"]["KeyPolicy"]["Statement"][0]
    assert statement["Resource"] == "*"  # the key's own ARN here would be a circular reference
    assert frag["DataKeyAlias"]["Properties"] == {"AliasName": "alias/platform", "TargetKeyId": {"Ref": "DataKey"}}


def test_the_bucket_is_private_encrypted_and_refuses_plain_http() -> None:
    frag = plain(secure_bucket("Data", key_arn="arn:key"))
    props = frag["DataBucket"]["Properties"]
    assert all(props["PublicAccessBlockConfiguration"].values()) and len(props["PublicAccessBlockConfiguration"]) == 4
    rule = props["BucketEncryption"]["ServerSideEncryptionConfiguration"][0]
    assert rule["ServerSideEncryptionByDefault"] == {"SSEAlgorithm": "aws:kms", "KMSMasterKeyID": "arn:key"}
    assert frag["DataBucket"]["DeletionPolicy"] == "Retain"
    policy = frag["DataBucketPolicy"]["Properties"]
    assert policy["Bucket"] == {"Ref": "DataBucket"}
    assert [s["Sid"] for s in policy["PolicyDocument"]["Statement"]] == ["DenyInsecureTransport"]
    assert "LifecycleConfiguration" not in props and "Tags" not in props


def test_allowed_principals_add_a_deny_for_everyone_else_and_lifecycle_is_optional() -> None:
    frag = plain(secure_bucket("Data", key_arn="k", allowed_principals=["arn:role/a", "arn:role/b-*"], archive_after_days=30))
    deny = frag["DataBucketPolicy"]["Properties"]["PolicyDocument"]["Statement"][1]
    assert deny["Effect"] == "Deny" and deny["Condition"] == {"StringNotLike": {"aws:PrincipalArn": ["arn:role/a", "arn:role/b-*"]}}
    rules = frag["DataBucket"]["Properties"]["LifecycleConfiguration"]["Rules"]
    assert rules[0]["Transitions"] == [{"StorageClass": "GLACIER", "TransitionInDays": 30}]


def test_tables_are_on_demand_with_recovery() -> None:
    both = plain(dynamodb_table("pk", "sk"))["Properties"]
    assert both["KeySchema"] == [{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}]
    assert both["BillingMode"] == "PAY_PER_REQUEST" and both["PointInTimeRecoverySpecification"] == {"PointInTimeRecoveryEnabled": True}
    one = plain(dynamodb_table("id", key_type="N", deletion_protection=False))["Properties"]
    assert one["KeySchema"] == [{"AttributeName": "id", "KeyType": "HASH"}]
    assert one["AttributeDefinitions"] == [{"AttributeName": "id", "AttributeType": "N"}]
    assert one["DeletionProtectionEnabled"] is False


def test_a_repository_policy_has_no_resource_and_exists_only_with_principals() -> None:
    assert "RepositoryPolicyText" not in plain(ecr_repository("app"))["Properties"]
    repo = plain(ecr_repository("app", pull_principals=["arn:role/pull"]))["Properties"]
    statement = repo["RepositoryPolicyText"]["Statement"][0]
    assert "Resource" not in statement and statement["Principal"] == {"AWS": "arn:role/pull"}
    two = plain(ecr_repository("app", pull_principals=["arn:role/a", "arn:role/b"]))["Properties"]
    assert two["RepositoryPolicyText"]["Statement"][0]["Principal"] == {"AWS": ["arn:role/a", "arn:role/b"]}
    assert repo["ImageTagMutability"] == "IMMUTABLE" and repo["ImageScanningConfiguration"] == {"ScanOnPush": True}


def test_publish_makes_one_parameter_per_value() -> None:
    frag = plain(publish("/p/s", {"key-arn": cfn.get_att("K", "Arn"), "bucket": "b"}))
    assert set(frag) == {"KeyArnParameter", "BucketParameter"}
    assert frag["KeyArnParameter"]["Properties"] == {"Type": "String", "Name": "/p/s/key-arn", "Value": {"Fn::GetAtt": ["K", "Arn"]}}


def test_the_producer_stack_is_closed_and_publishes_what_the_consumer_reads() -> None:
    template = plain(data_platform.build())
    names = set(template["Resources"]) | set(template["Parameters"])
    assert refs(template["Resources"]) <= names
    published = {r["Properties"]["Name"] for r in template["Resources"].values() if r["Type"] == "AWS::SSM::Parameter"}
    consumer = plain(data_consumer.build())
    read = {p["Default"] for p in consumer["Parameters"].values()}
    assert read <= published  # everything the consumer looks up, the producer publishes


def test_the_consumer_reads_through_parameters_and_the_grant_covers_bucket_and_objects() -> None:
    template = plain(data_consumer.build())
    assert refs(template["Resources"]) <= set(template["Parameters"])
    statements = template["Resources"]["ReaderRole"]["Properties"]["Policies"][0]["PolicyDocument"]["Statement"]
    assert statements[0]["Resource"][0] == {"Ref": "DataBucketArn"}
    assert statements[0]["Resource"][1] == {"Fn::Join": ["", [{"Ref": "DataBucketArn"}, "/*"]]}
    assert statements[1] == {"Effect": "Allow", "Action": ["kms:Decrypt", "kms:DescribeKey"], "Resource": {"Ref": "DataKeyArn"}}
