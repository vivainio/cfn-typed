"""`cfn-typed import --sls`: the generated module renders the template it was made from, and uses sls.* where it can."""

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from cfn_typed_sumo import sls, sls_import

import cfn_typed as cfn
from cfn_typed.cli import main

EXAMPLE = Path(__file__).parent.parent / "examples" / "serverless_eject"
TYPES = "cfn_typed_sumo.types"


def load(name: str) -> dict[str, Any]:
    return json.loads((EXAMPLE / name).read_text())


def render(source: str) -> dict[str, Any]:
    namespace: dict[str, Any] = {}
    exec(compile(source, "<imported>", "exec"), namespace)  # noqa: S102 (the module this test just generated)
    return namespace["build"]()


@pytest.mark.parametrize("name", ["original.json", "original_api.json"])
def test_the_example_templates_come_back_exactly_and_as_sls_calls(name: str) -> None:
    original = load(name)
    source = sls_import.to_python(original, TYPES)
    assert render(source) == original
    assert "Left as plain resources" not in source or name == "original_api.json"
    assert "sls.function(" in source and "sls.iam_role(" in source and "sls.deployment_bucket()" in source


def test_the_api_example_is_written_as_the_calls_a_person_would_write() -> None:
    source = sls_import.to_python(load("original_api.json"), TYPES)
    for call in ("sls.rest_api(", "sls.http_api(", "sls.sqs_event(", "sls.sqs_statement(", "sls.JwtAuthorizer(", "sls.endpoint_outputs(", "sls.outputs("):
        assert call in source, call
    assert 'sls.Route("/todos/{id}", "GET", "todos")' in source
    assert "ConsumerEventSourceMappingSQSOrdersQueue" not in source  # claimed by sls.sqs_event
    assert "OrdersQueue" in source  # the queue itself is a plain resource


def test_a_group_that_differs_stays_as_plain_resources_and_the_template_is_unchanged() -> None:
    original = load("original.json")
    changed = copy.deepcopy(original)
    changed["Resources"]["WorkerLambdaFunction"]["Properties"]["KmsKeyArn"] = "arn:aws:kms:eu-west-1:111111111111:key/abc"
    source = sls_import.to_python(changed, TYPES)
    assert render(source) == changed
    assert "WorkerLambdaFunction" in source and "sls.function(" not in source
    assert "sls.iam_role(" in source and "sls.deployment_bucket()" in source  # the rest of the service is still recognised


def test_a_vpc_stream_sns_and_binary_media_service_comes_back() -> None:
    original = load("original_api.json")
    resources = original["Resources"]
    # a function in a VPC, as the framework writes it: VpcConfig on the function and the interface statement in the role
    resources["TodosLambdaFunction"]["Properties"]["VpcConfig"] = {"SecurityGroupIds": ["sg-1"], "SubnetIds": ["subnet-a", "subnet-b"]}
    statements = resources["IamRoleLambdaExecution"]["Properties"]["Policies"][0]["PolicyDocument"]["Statement"]
    statements.append(sls.vpc_statement())
    resources["ApiGatewayRestApi"]["Properties"]["BinaryMediaTypes"] = ["image/*"]
    resources["SNSTopicAlerts"] = {"Type": "AWS::SNS::Topic", "Properties": {"TopicName": "alerts"}}
    resources["Orders"] = {"Type": "AWS::DynamoDB::Table", "Properties": {"TableName": "orders"}}
    resources.update(sls.sns_event("users", "SNSTopicAlerts"))
    resources.update(sls.stream_event("users", "Orders"))
    statements.append(sls.stream_statement("dynamodb", {"Fn::GetAtt": ["Orders", "StreamArn"]}))
    source = sls_import.to_python(original, TYPES)
    assert render(source) == original
    for call in ("sls.Vpc(", "sls.vpc_statement()", "binary_media_types=", "sls.sns_event(", "sls.stream_event(", "sls.stream_statement("):
        assert call in source, call


def test_the_older_frameworks_log_statement_is_kept_through_log_actions() -> None:
    original = load("original.json")
    statements = original["Resources"]["IamRoleLambdaExecution"]["Properties"]["Policies"][0]["PolicyDocument"]["Statement"]
    statements[0]["Action"] = ["logs:CreateLogStream", "logs:CreateLogGroup"]
    source = sls_import.to_python(original, TYPES)
    assert render(source) == original and "log_actions=" in source


def test_a_service_without_functions_is_the_plain_import() -> None:
    """Most of the framework's stacks are a bucket and its policy, written under `resources:`: nothing for `sls` to claim."""
    template = {"AWSTemplateFormatVersion": "2010-09-09", "Resources": {
        "AppBucket": {"Type": "AWS::S3::Bucket", "Properties": {"BucketName": "default-stage-site"}},
        "AppBucketPolicy": {"Type": "AWS::S3::BucketPolicy", "Properties": {
            "Bucket": {"Ref": "AppBucket"},
            "PolicyDocument": {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": {"AWS": ["arn:aws:iam::cloudfront:user/CloudFront Origin Access Identity default-identity"]},
                                                                       "Action": ["s3:GetObject"], "Resource": [{"Fn::Sub": "${AppBucket.Arn}/*"}]}]},
        }},
    }, "Outputs": {"AppBucketName": {"Value": {"Ref": "AppBucket"}}}}
    source, claimed = sls_import.import_sls(template, TYPES)
    assert claimed == 0 and "sls." not in source and render(source) == template


def test_a_service_with_its_own_role_bucket_and_names_and_no_versions_comes_back() -> None:
    """`provider.iam.role`, `provider.deploymentBucket.name`, `versionFunctions: false` and `functions.x.name`: no role, bucket or version of the framework's."""
    fn = sls.function("Runner", name="approval-runner", bucket="shared-workbucket-eu-west-1", versioned=False, role=cfn.get_att("RunnerRole", "Arn"),
                      s3_key="data/approvals/default-stage/1/runner.zip", handler="runner.handle", runtime="python3.12", memory=1536, timeout=900,
                      environment={"stage": "default-stage"}, tags=[{"Key": "Owner", "Value": "team"}])
    template: dict[str, Any] = {"AWSTemplateFormatVersion": "2010-09-09", "Resources": {
        **fn.resources,
        "RunnerRole": {"Type": "AWS::IAM::Role", "Properties": {"RoleName": "RunnerRole", "AssumeRolePolicyDocument": {"Version": "2012-10-17", "Statement": []}}},
    }, "Outputs": {"ExecArn": {"Value": {"Fn::GetAtt": ["RunnerLambdaFunction", "Arn"]}}}}
    source, claimed = sls_import.import_sls(template, TYPES)
    assert claimed == len(fn.resources) == 2  # the log group and the function
    assert render(source) == template
    for text in ('name="approval-runner"', 'bucket="shared-workbucket-eu-west-1"', "versioned=False", "role=cfn.get_att"):
        assert text in source, text
    assert "SERVICE" not in source and "LambdaVersion" not in source


def test_a_versioned_function_needs_its_hash_and_a_name_needs_service_or_name() -> None:
    with pytest.raises(ValueError, match="code_sha256 and version_id"):
        sls.function("w", service="s", stage="d", s3_key="k", handler="h", runtime="python3.12")
    with pytest.raises(ValueError, match="service and stage"):
        sls.function("w", versioned=False, s3_key="k", handler="h", runtime="python3.12")


def test_the_command_writes_a_module(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "stack.py"
    assert main(argv=["import", "--sls", str(EXAMPLE / "original.json"), "-o", str(out), "--types", TYPES], prog="cfn-typed") == 0
    assert render(out.read_text()) == load("original.json")
    assert main(argv=["import", "--sls", str(EXAMPLE / "original.json"), "--types", TYPES], prog="cfn-typed") == 0
    assert "sls.function(" in capsys.readouterr().out
    plain = tmp_path / "plain.json"
    plain.write_text(json.dumps({"Resources": {"Q": {"Type": "AWS::SQS::Queue", "Properties": {}}}}))
    assert main(argv=["import", "--sls", str(plain)], prog="cfn-typed") == 0
    captured = capsys.readouterr()
    assert "nothing to write as a call" in captured.err and "sls." not in captured.out
