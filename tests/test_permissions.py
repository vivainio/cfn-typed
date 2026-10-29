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


def test_only_exact_actions_are_names_patterns_belong_to_grants() -> None:
    values = [v for names in services().values() for v in names.values()]
    assert not [v for v in values if "*" in v]
    assert S3.GetObject == "s3:GetObject" and not hasattr(S3, "GetObject_All")


def test_every_attribute_is_consistent_with_its_value() -> None:
    all_names = services()
    assert len(all_names) == 11 and sum(map(len, all_names.values())) > 800
    seen: set[str] = set()
    for cls, names in all_names.items():
        prefix = PREFIX.get(cls, cls.lower())
        for attr, action in names.items():
            assert re.fullmatch(r"[a-z0-9-]+:[A-Za-z][A-Za-z0-9]*", action), action
            assert action.startswith(prefix + ":"), (cls, action)
            assert attr == action.split(":", 1)[1], (attr, action)
            assert action not in seen, f"duplicate {action}"
            seen.add(action)


def test_names_go_straight_into_a_policy_statement() -> None:
    statement = cfn.allow([Sqs.ReceiveMessage, Sqs.DeleteMessage], [cfn.get_att("Q", "Arn")])
    assert json.loads(json.dumps(statement))["Action"] == ["sqs:ReceiveMessage", "sqs:DeleteMessage"]


def test_the_source_is_credited_and_the_pin_matches() -> None:
    doc = permissions.__doc__ or ""
    for phrase in ("awacs", "BSD-2-Clause", "Mark Peek", "NOTICE", "Service Authorization Reference"):
        assert phrase in doc, phrase
    version = re.search(r"awacs (\d+\.\d+\.\d+)", doc)
    assert version
    script = (ROOT / "scripts" / "sync-permissions.py").read_text()
    pin = re.search(r'dependencies = \["awacs==(\d+\.\d+\.\d+)"\]', script)
    assert pin and pin.group(1) == version.group(1)  # regenerate after bumping the pin
    notice = (ROOT / "NOTICE").read_text()
    assert "Mark Peek" in notice and "Amazon.com" in notice
    assert "Redistribution and use" in (ROOT / "licenses" / "AWACS-LICENSE.txt").read_text()
    assert "Apache License" in (ROOT / "licenses" / "AWS-CDK-LICENSE.txt").read_text()
    assert "awacs" not in (ROOT / "pyproject.toml").read_text()  # a tool for one script, never a dependency
