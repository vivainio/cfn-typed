import dataclasses
import re
from pathlib import Path
from typing import Any

import pytest

import cfn_typed as cfn
from cfn_typed import grants, permissions

ROOT = Path(__file__).parent.parent
ARN: cfn.Expr[str] = cfn.get_att("B", "Arn")


def all_grants() -> list[tuple[str, grants.Grant]]:
    found = []
    for service in grants.__all__:
        cls = getattr(grants, service, None)
        if not isinstance(cls, type):
            continue
        for resource, resource_cls in vars(cls).items():
            if isinstance(resource_cls, type):
                for name, grant in vars(resource_cls).items():
                    if isinstance(grant, grants.Grant):
                        found.append((f"{service}.{resource}.{name}", grant))
    return found


def test_sqs_consume_is_the_cdk_set_with_an_optional_key_statement() -> None:
    plain = grants.Sqs.Queue.consume_messages.on("arn:q")
    assert plain == [{
        "Effect": "Allow", "Resource": ["arn:q"],
        "Action": ["sqs:ReceiveMessage", "sqs:ChangeMessageVisibility", "sqs:GetQueueUrl", "sqs:DeleteMessage", "sqs:GetQueueAttributes"],
    }]
    with_key = grants.Sqs.Queue.consume_messages.on("arn:q", key_arn="arn:key")
    assert with_key[1] == {"Effect": "Allow", "Action": ["kms:Decrypt"], "Resource": "arn:key"}
    assert len(grants.Sqs.Queue.send_messages.on("arn:q", key_arn="arn:key")[1]["Action"]) == 4
    assert len(grants.Sqs.Queue.purge.on("arn:q", key_arn="arn:key")) == 1  # a grant with no key actions ignores key_arn


def test_s3_bucket_and_object_shapes() -> None:
    read = grants.S3.Bucket.read.on("arn:b")[0]
    assert read["Resource"] == ["arn:b", "arn:b/*"]
    assert grants.S3.Bucket.read.on("arn:b", keys="uploads/*")[0]["Resource"] == ["arn:b", "arn:b/uploads/*"]
    assert grants.S3.Bucket.put.on("arn:b")[0]["Resource"] == ["arn:b/*"]  # objects only
    assert grants.S3.Bucket.delete.on("arn:b")[0]["Action"] == ["s3:DeleteObject*"]
    assert [p["Action"] for p in grants.S3.Bucket.read.on("arn:b", key_arn="k")][1] == ["kms:Decrypt", "kms:DescribeKey"]


def test_an_intrinsic_arn_gets_a_join_for_its_children() -> None:
    resources: Any = grants.S3.Bucket.read.on(ARN)[0]["Resource"]
    assert resources[0] == ARN
    assert resources[1] == {"Fn::Join": ["", [ARN, "/*"]]}
    assert grants.S3.Bucket.put.on(ARN)[0]["Resource"] == [{"Fn::Join": ["", [ARN, "/*"]]}]


def test_dynamodb_indexes_and_the_any_shape() -> None:
    table = grants.DynamoDb.Table
    assert table.read_data.on("arn:t")[0]["Resource"] == ["arn:t"]
    assert table.read_data.on("arn:t", indexes=True)[0]["Resource"] == ["arn:t", "arn:t/index/*"]
    assert "dynamodb:DescribeTable" in table.write_data.on("arn:t")[0]["Action"]
    assert table.full_access.actions == ("dynamodb:*",)
    assert table.list_streams.on()[0]["Resource"] == ["*"]
    assert grants.Events.EventBus.all_put_events.on()[0]["Resource"] == ["*"]


def test_misuse_is_an_error() -> None:
    with pytest.raises(ValueError, match="needs the ARN"):
        grants.Sqs.Queue.purge.on()
    with pytest.raises(ValueError, match="takes no ARN"):
        grants.DynamoDb.Table.list_streams.on("arn:t")
    with pytest.raises(ValueError, match="indexes"):
        grants.Sqs.Queue.purge.on("arn:q", indexes=True)
    with pytest.raises(ValueError, match="keys"):
        grants.Sqs.Queue.purge.on("arn:q", keys="x/*")
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(grants.Sqs.Queue.purge, "actions", ())


def test_every_grant_is_built_from_permission_names() -> None:
    names = {v for cls in vars(permissions).values() if isinstance(cls, type) for v in vars(cls).values() if isinstance(v, str)}
    found = all_grants()
    assert len(found) >= 30
    for where, grant in found:
        assert grant.actions and len(set(grant.actions)) == len(grant.actions), where
        assert set(grant.actions) <= names and set(grant.key_actions) <= names, where
        assert all(a.startswith("kms:") for a in grant.key_actions), where
        assert grant.shape in ("arn", "arn_and_indexes", "arn_and_objects", "objects", "any"), where


def test_statements_become_a_policy_document() -> None:
    document = cfn.policy_document([*grants.Sqs.Queue.consume_messages.on("arn:q"), *grants.Lambda.Function.invoke.on("arn:f")])
    assert document["Version"] == "2012-10-17" and len(document["Statement"]) == 2
    assert "Action:" in cfn.to_yaml({"Resources": {}, "Mappings": {"P": dict(document)}})


def test_the_layer_says_it_is_opinion_unstable_and_credits_the_cdk() -> None:
    doc = grants.__doc__ or ""
    for phrase in ("Opinion layer", "unstable", "AWS CDK", "Apache-2.0", "NOTICE"):
        assert phrase in doc, phrase
    generated = (ROOT / "src" / "cfn_typed" / "_cdk_grants.py").read_text()
    sha = re.search(r"commit ([0-9a-f]{40})", generated)
    assert sha
    pins = set()
    for name in ("sync-cdk-grants.py", "sync-cdk-permissions.py"):
        pin = re.search(r'PINNED_SHA = "([0-9a-f]{40})"', (ROOT / "scripts" / name).read_text())
        assert pin, name
        pins.add(pin.group(1))
    assert pins == {sha.group(1)}  # names and grants must come from the same CDK commit
