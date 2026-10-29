import json
import re
from pathlib import Path

import cfn_typed as cfn
from cfn_typed import permissions
from cfn_typed.permissions import DynamoDb, Kms, S3, Sqs

ROOT = Path(__file__).parent.parent
PREFIX = {"DynamoDb": "dynamodb", "SecretsManager": "secretsmanager"}  # classes whose prefix is not just the lowercased name


def services() -> dict[str, dict[str, str]]:
    return {
        name: {k: v for k, v in vars(cls).items() if not k.startswith("_") and isinstance(v, str)}
        for name, cls in vars(permissions).items()
        if isinstance(cls, type)
    }


def test_names_are_the_iam_action_strings() -> None:
    assert Sqs.ReceiveMessage == "sqs:ReceiveMessage"
    assert DynamoDb.PutItem == "dynamodb:PutItem"
    assert Kms.Decrypt == "kms:Decrypt"


def test_a_star_in_the_action_becomes_all() -> None:
    assert S3.GetObject_All == "s3:GetObject*"
    assert S3.GetObject_All != S3.GetBucket_All


def test_every_attribute_is_consistent_with_its_value() -> None:
    all_names = services()
    assert len(all_names) >= 10 and sum(map(len, all_names.values())) > 80
    seen: set[str] = set()
    for cls, names in all_names.items():
        prefix = PREFIX.get(cls, cls.lower())
        for attr, action in names.items():
            assert re.fullmatch(r"[a-z0-9-]+:[A-Za-z0-9*]+", action), action
            assert action.startswith(prefix + ":"), (cls, action)
            tail = action.split(":", 1)[1]
            assert attr == ("All" if tail == "*" else tail.replace("*", "_All")), (attr, action)
            assert action not in seen, f"duplicate {action}"
            seen.add(action)


def test_names_go_straight_into_a_policy_statement() -> None:
    statement = cfn.allow([Sqs.ReceiveMessage, Sqs.DeleteMessage], [cfn.get_att("Q", "Arn")])
    assert json.loads(json.dumps(statement))["Action"] == ["sqs:ReceiveMessage", "sqs:DeleteMessage"]


def test_the_source_is_credited_and_the_pin_matches() -> None:
    doc = permissions.__doc__ or ""
    assert "AWS CDK" in doc and "Apache License 2.0" in doc and "NOTICE" in doc
    sha = re.search(r"commit ([0-9a-f]{40})", doc)
    assert sha
    pinned = re.search(r'PINNED_SHA = "([0-9a-f]{40})"', (ROOT / "scripts" / "sync-cdk-permissions.py").read_text())
    assert pinned and pinned.group(1) == sha.group(1)  # regenerate after changing the pin
    assert "Amazon.com" in (ROOT / "NOTICE").read_text()
    assert "Apache License" in (ROOT / "licenses" / "AWS-CDK-LICENSE.txt").read_text()
