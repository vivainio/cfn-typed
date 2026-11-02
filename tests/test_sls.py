"""The framework's resources that `cfn_typed_sumo.sls` writes beyond the two example services."""

from typing import Any

import pytest
from cfn_typed_sumo import sls

import cfn_typed as cfn
from cfn_typed.testing import assert_references_resolve



def function(key: str, **extra: Any) -> sls.Function:
    return sls.function(key, service="shop", stage="dev", s3_key="k.zip", handler="h.run", runtime="python3.12", code_sha256="x", version_id="V1", **extra)


def test_a_vpc_writes_vpc_config_and_the_role_needs_the_interface_actions() -> None:
    vpc = sls.Vpc(["sg-1"], [cfn.import_value("subnet-a"), "subnet-b"])
    fn = function("worker", vpc=vpc, layers=["arn:layer"], description="d", reserved_concurrency=2)
    props = fn.resources["WorkerLambdaFunction"]["Properties"]
    assert props["VpcConfig"] == {"SecurityGroupIds": ["sg-1"], "SubnetIds": [{"Fn::ImportValue": "subnet-a"}, "subnet-b"]}
    assert props["Layers"] == ["arn:layer"] and props["Description"] == "d" and props["ReservedConcurrentExecutions"] == 2
    statement: Any = sls.vpc_statement()
    assert statement["Resource"] == "*" and "ec2:CreateNetworkInterface" in statement["Action"]
    role = sls.iam_role("shop", "dev", [statement])["IamRoleLambdaExecution"]["Properties"]["Policies"][0]["PolicyDocument"]["Statement"]
    assert role[-1] == statement


def test_the_log_statement_of_an_older_framework_has_no_tag_resource() -> None:
    role = sls.iam_role("shop", "dev", log_actions=["logs:CreateLogStream", "logs:CreateLogGroup"])["IamRoleLambdaExecution"]
    assert role["Properties"]["Policies"][0]["PolicyDocument"]["Statement"][0]["Action"] == ["logs:CreateLogStream", "logs:CreateLogGroup"]


def test_an_sns_event_is_a_subscription_and_a_permission() -> None:
    out = sls.sns_event("approve", "SNSTopicApprovals")
    assert list(out) == ["ApproveSnsSubscriptionApprovals", "ApproveLambdaPermissionApprovalsSNS"]
    assert out["ApproveSnsSubscriptionApprovals"]["Properties"]["Protocol"] == "lambda"
    assert out["ApproveLambdaPermissionApprovalsSNS"]["Properties"]["Principal"] == "sns.amazonaws.com"
    assert list(sls.sns_event("approve", "T", name="Other")) == ["ApproveSnsSubscriptionOther", "ApproveLambdaPermissionOtherSNS"]


def test_a_stream_event_reads_the_stream_arn_and_has_a_statement() -> None:
    table = sls.stream_event("tail", "Orders")
    (mapping,) = table.values()
    assert list(table) == ["TailEventSourceMappingDynamodbOrders"]
    assert mapping["Properties"]["EventSourceArn"] == {"Fn::GetAtt": ["Orders", "StreamArn"]} and mapping["Properties"]["StartingPosition"] == "TRIM_HORIZON"
    kinesis = sls.stream_event("tail", "Feed", kind="kinesis", batch_size=100)
    assert list(kinesis) == ["TailEventSourceMappingKinesisFeed"]
    assert next(iter(kinesis.values()))["Properties"]["EventSourceArn"] == {"Fn::GetAtt": ["Feed", "Arn"]}
    stream_statement: Any = sls.stream_statement("kinesis", cfn.get_att("Feed", "Arn"))
    assert stream_statement["Action"][0] == "kinesis:GetRecords"
    with pytest.raises(ValueError, match="dynamodb or kinesis"):
        sls.stream_event("tail", "X", kind="sqs")


def test_binary_media_types_go_on_the_rest_api() -> None:
    out = sls.rest_api("shop", "dev", [sls.Route("/files", "GET", "files")], binary_media_types=["image/*", "application/pdf"])
    assert out["ApiGatewayRestApi"]["Properties"]["BinaryMediaTypes"] == ["image/*", "application/pdf"]
    assert "BinaryMediaTypes" not in sls.rest_api("shop", "dev", [sls.Route("/files", "GET", "files")])["ApiGatewayRestApi"]["Properties"]


def test_a_route_with_an_authorizer_is_custom_authorized() -> None:
    out = sls.rest_api(
        "shop", "dev", [sls.Route("/todos", "GET", "todos", authorizer="auth"), sls.Route("/open", "GET", "todos")],
        authorizers={"auth": sls.Authorizer("check", result_ttl=0)},
    )
    authorizer = out["AuthApiGatewayAuthorizer"]["Properties"]
    assert authorizer["Type"] == "TOKEN" and authorizer["AuthorizerResultTtlInSeconds"] == 0 and authorizer["IdentitySource"] == "method.request.header.Authorization"
    guarded = out["ApiGatewayMethodTodosGet"]
    assert guarded["Properties"]["AuthorizationType"] == "CUSTOM" and guarded["Properties"]["AuthorizerId"] == {"Ref": "AuthApiGatewayAuthorizer"}
    assert guarded["DependsOn"] == "AuthApiGatewayAuthorizer"
    assert out["ApiGatewayMethodOpenGet"]["Properties"]["AuthorizationType"] == "NONE" and "DependsOn" not in out["ApiGatewayMethodOpenGet"]
    assert "CheckLambdaPermissionApiGateway" in out
    with pytest.raises(ValueError, match="not in authorizers"):
        sls.rest_api("shop", "dev", [sls.Route("/todos", "GET", "todos", authorizer="nope")])


def test_the_new_pieces_make_a_template_whose_references_resolve() -> None:
    worker = function("worker", vpc=sls.Vpc(["sg-1"], ["subnet-a"]))
    check = function("check")
    template: cfn.Template = {"Resources": cfn.combine(
        sls.deployment_bucket(),
        sls.iam_role("shop", "dev", [sls.vpc_statement(), sls.stream_statement("dynamodb", cfn.get_att("Orders", "StreamArn"))]),
        worker, check,
        {"SNSTopicApprovals": {"Type": "AWS::SNS::Topic", "Properties": {}}, "Orders": {"Type": "AWS::DynamoDB::Table", "Properties": {}}},
        sls.sns_event("worker", "SNSTopicApprovals"),
        sls.stream_event("worker", "Orders"),
        sls.rest_api("shop", "dev", [sls.Route("/a", "GET", "worker", authorizer="auth")], authorizers={"auth": sls.Authorizer("check")}),
    )}
    assert_references_resolve(template)
