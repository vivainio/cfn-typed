from typing import Any

import pytest

from cfn_typed.adopt import find_adopt_problems, primary_identifier, resources_to_import
from cfn_typed.changes import plan

SCHEMAS = [
    {"typeName": "AWS::ApiGateway::DomainName", "primaryIdentifier": ["/properties/DomainName"]},
    {"typeName": "AWS::ApiGateway::BasePathMapping", "primaryIdentifier": ["/properties/DomainName", "/properties/BasePath"]},
]
TEMPLATE: dict[str, Any] = {"Resources": {
    "Domain": {"Type": "AWS::ApiGateway::DomainName", "DeletionPolicy": "Retain", "Properties": {"DomainName": "api.example.com"}},
    "Mapping": {"Type": "AWS::ApiGateway::BasePathMapping", "DeletionPolicy": "Retain", "Properties": {"DomainName": "api.example.com"}},
    "Loose": {"Type": "AWS::ApiGateway::DomainName", "Properties": {}},
    "Queue": {"Type": "AWS::SQS::Queue"},
}}
IDS = {"Domain": {"DomainName": "api.example.com"}, "Mapping": {"DomainName": "api.example.com", "BasePath": "(none)"}}


def test_the_identifier_is_what_the_schema_says() -> None:
    assert primary_identifier("AWS::ApiGateway::BasePathMapping", SCHEMAS) == ["DomainName", "BasePath"]
    assert primary_identifier("AWS::Nope::Thing", SCHEMAS) is None


def test_the_import_list_is_built_when_nothing_is_wrong() -> None:
    assert resources_to_import(TEMPLATE, IDS, SCHEMAS) == [
        {"ResourceType": "AWS::ApiGateway::DomainName", "LogicalResourceId": "Domain", "ResourceIdentifier": {"DomainName": "api.example.com"}},
        {"ResourceType": "AWS::ApiGateway::BasePathMapping", "LogicalResourceId": "Mapping", "ResourceIdentifier": {"DomainName": "api.example.com", "BasePath": "(none)"}},
    ]


def test_every_problem_is_listed() -> None:
    problems = find_adopt_problems(TEMPLATE, {"Gone": {"X": "1"}, "Loose": {"Name": "x"}, "Queue": {"QueueUrl": "u"}}, SCHEMAS)
    assert problems == [
        "Gone: not a resource in the template",
        "Loose (AWS::ApiGateway::DomainName): the identifier is DomainName, not Name",
        "Loose: an imported resource needs a DeletionPolicy (Retain)",
        "Queue: no registry schema for AWS::SQS::Queue",
        "Queue: an imported resource needs a DeletionPolicy (Retain)",
    ]
    with pytest.raises(ValueError, match="Gone: not a resource"):
        resources_to_import(TEMPLATE, {"Gone": {}}, SCHEMAS)


def test_an_import_change_set_is_made_with_the_list_and_kept() -> None:
    calls: list[list[str]] = []

    def run(args):
        calls.append(list(args))
        if args[1] == "describe-change-set":
            return {"Status": "CREATE_COMPLETE", "Changes": [{"ResourceChange": {"Action": "Import", "LogicalResourceId": "Domain", "ResourceType": "AWS::ApiGateway::DomainName"}}]}

    found = plan("ledger-dev", TEMPLATE, runner=run, resources_to_import=resources_to_import(TEMPLATE, IDS, SCHEMAS), keep=True, change_set_name="adopt")
    assert [c.action for c in found] == ["Import"]
    create = calls[0]
    assert "IMPORT" in create and "--resources-to-import" in create and create[create.index("--change-set-name") + 1] == "adopt"
    assert "delete-change-set" not in [c[1] for c in calls]
