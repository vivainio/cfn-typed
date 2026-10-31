"""`sam.expand` against AWS's own SAM translator (the dev dependency `aws-sam-translator`, same release as the types)."""

import copy
import json
import re
from typing import Any

import pytest
from cfn_typed import allow, get_att, ref
from cfn_typed.testing import assert_template_ok

from cfn_typed_sumo import sam
from cfn_typed_sumo.types import dynamodb, kinesis, s3, serverless, sns, sqs


def template() -> Any:
    return sam.template(
        {
            "Orders": sqs.queue(),
            "Worker": sam.function(
                handler="app.h", code_uri="s3://bucket/key.zip", memory=256, environment={"A": "b"},
                events={
                    "Q": sam.sqs_event(get_att("Orders", "Arn"), max_batching_window=5),
                    "Nightly": sam.schedule_event("rate(1 day)"),
                },
                statements=[allow("dynamodb:GetItem", "*")], managed_policies=["AWSLambdaBasicExecutionRole"],
            ),
            "Table": sam.table("pk", "Number"),
        },
        function_globals={"Runtime": "python3.12", "Timeout": 30},
    )


@pytest.fixture(autouse=True)
def region(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")  # the translator wants one, and makes no calls


def translate(tpl: Any) -> dict[str, Any]:
    """What SAM itself makes of `tpl`, offline."""
    translator = pytest.importorskip("samtranslator.translator.translator")
    parser = pytest.importorskip("samtranslator.parser.parser")

    policies = {n: f"arn:aws:iam::aws:policy/service-role/{n}" for n in ("AWSLambdaBasicExecutionRole", "AWSLambdaSQSQueueExecutionRole")}
    out = translator.Translator(policies, parser.Parser()).translate(copy.deepcopy(dict(tpl)), {})
    return out["Resources"]


def normal(value: Any) -> Any:
    """Differences that are only spelling: `${AWS::Partition}`, a `Version` on an inline policy, one Service as a list, SAM's tags."""
    if isinstance(value, dict):
        if set(value) == {"Fn::Sub"} and isinstance(value["Fn::Sub"], str):
            return value["Fn::Sub"].replace("${AWS::Partition}", "aws")
        if set(value) == {"Fn::Join"} and value["Fn::Join"][0] == "\n" and all(isinstance(x, str) for x in value["Fn::Join"][1]):
            return "\n".join(value["Fn::Join"][1])
        out = {k: normal(v) for k, v in value.items() if (k != "Version" or "Statement" not in value) and value[k] != []}
        if isinstance(out.get("DefinitionString"), str):
            out["DefinitionString"] = json.loads(out["DefinitionString"])
        if isinstance(out.get("Service"), str):
            out["Service"] = [out["Service"]]
        if isinstance(out.get("Tags"), list):
            out["Tags"] = [t for t in out["Tags"] if t.get("Value") != "SAM"] or None
            if out["Tags"] is None:
                del out["Tags"]
        return out
    if isinstance(value, list):
        items = [normal(v) for v in value]
        return sorted(items, key=lambda v: json.dumps(v, sort_keys=True)) if all(isinstance(i, str) for i in items) else items
    return value


def test_expand_has_no_transform_and_no_globals() -> None:
    out = sam.expand(template())
    assert "Transform" not in out and "Globals" not in out
    assert not any(r["Type"].startswith("AWS::Serverless::") for r in out["Resources"].values())
    assert "SAM" not in json.dumps(out) and "Serverless" not in json.dumps(out)
    assert_template_ok(out)


@pytest.mark.parametrize("logical", ["Worker", "WorkerRole", "WorkerQ", "WorkerNightly", "WorkerNightlyPermission", "Table", "Orders"])
def test_expand_matches_the_sam_translator_resource_by_resource(logical: str) -> None:
    tpl = template()
    ours, theirs = sam.expand(tpl)["Resources"], translate(tpl)
    assert logical in ours and logical in theirs, "logical IDs must match SAM's, or a migration replaces the resource"
    assert normal(ours[logical]) == normal(theirs[logical])


def test_every_plain_resource_sam_makes_for_these_events_is_there() -> None:
    tpl = template()
    ours = sam.expand(tpl)["Resources"]
    assert set(translate(tpl)) <= set(ours)


def test_http_api_events_become_plain_apigateway_resources_without_openapi() -> None:
    tpl = sam.template({"Web": sam.function(handler="h", code_uri="s3://b/k.zip", events={
        "Get": sam.http_api_event("/orders", "get"), "Post": sam.http_api_event("/orders", "POST")})})
    out = sam.expand(tpl)["Resources"]
    assert {r["Type"] for r in out.values()} >= {"AWS::ApiGatewayV2::Api", "AWS::ApiGatewayV2::Route", "AWS::ApiGatewayV2::Integration", "AWS::ApiGatewayV2::Stage"}
    assert sorted(r["Properties"]["RouteKey"] for r in out.values() if r["Type"] == "AWS::ApiGatewayV2::Route") == ["GET /orders", "POST /orders"]
    assert "Body" not in json.dumps(out)
    assert_template_ok(sam.expand(tpl))


def test_globals_merge_and_ignore_globals() -> None:
    tpl = sam.template(
        {"A": sam.function(handler="h", code_uri="s3://b/k.zip", environment={"X": "1"}),
         "B": serverless.function(Handler="h", CodeUri="s3://b/k.zip", ignore_globals=["Timeout"])},
        function_globals={"Runtime": "python3.12", "Timeout": 9, "Environment": {"Variables": {"G": "g"}}},
    )
    out = sam.expand(tpl)["Resources"]
    assert out["A"]["Properties"]["Environment"] == {"Variables": {"G": "g", "X": "1"}}
    assert out["A"]["Properties"]["Timeout"] == 9
    assert "Timeout" not in out["B"]["Properties"]


def test_unsupported_things_are_errors_not_silently_dropped() -> None:
    with pytest.raises(NotImplementedError, match="s3://"):
        sam.expand(sam.template({"F": sam.function(handler="h", code_uri="src/")}))
    with pytest.raises(NotImplementedError, match="AWS::Serverless::LayerVersion"):
        sam.expand({"Resources": {"S": {"Type": "AWS::Serverless::LayerVersion", "Properties": {}}}})
    with pytest.raises(NotImplementedError, match="Tracing"):
        sam.expand({"Resources": {"F": {"Type": "AWS::Serverless::Function", "Properties": {"Handler": "h", "CodeUri": "s3://b/k", "Tracing": "Active"}}}})
    with pytest.raises(NotImplementedError, match="S3"):
        sam.expand({"Resources": {"F": {"Type": "AWS::Serverless::Function", "Properties": {"Handler": "h", "CodeUri": "s3://b/k", "Events": {"K": {"Type": "S3", "Properties": {}}}}}}})


def test_other_resources_and_template_keys_pass_through() -> None:
    tpl = sam.template({"Orders": sqs.queue()}, description="d")
    out = sam.expand(tpl)
    assert out["Resources"] == tpl["Resources"] and out["Description"] == "d"
    assert re.fullmatch(r"\d{4}-\d\d-\d\d", out["AWSTemplateFormatVersion"])


def connector_template(destination: Any, permissions: Any) -> Any:
    return sam.template({
        "Q": sqs.queue(), "B": s3.bucket(), "Topic": sns.topic(), "Table": sam.table("pk"),
        "F": sam.function(handler="h", code_uri="s3://b/k.zip", runtime="python3.12"),
        "G": sam.function(handler="h", code_uri="s3://b/k.zip", runtime="python3.12"),
        **sam.connect("C", "F", destination, permissions),
    })


@pytest.mark.parametrize(("destination", "permissions"), [
    ("Q", ["Read"]), ("Q", ["Write"]), ("Q", ["Read", "Write"]), ("Table", ["Read", "Write"]), ("B", ["Read"]),
    ("B", ["Write"]), ("G", ["Write"]), ("Topic", ["Write"]), (["Q", "Table"], ["Read"]),
])
def test_connectors_expand_to_what_sam_makes(destination: Any, permissions: Any) -> None:
    tpl = connector_template(destination, permissions)
    ours, theirs = sam.expand(tpl)["Resources"], translate(tpl)
    policies = {k for k, v in theirs.items() if v["Type"] == "AWS::IAM::ManagedPolicy"}
    assert policies and policies <= set(ours), "logical IDs must match SAM's"
    for key in policies:
        theirs[key].pop("Metadata", None)  # SAM's bookkeeping, which names SAM
        assert normal(ours[key]) == normal(theirs[key])
    assert "SAM" not in json.dumps(sam.expand(tpl)) and "Serverless" not in json.dumps(sam.expand(tpl))


def test_connector_outside_the_table_is_an_error() -> None:
    tpl = sam.template({"F": sam.function(handler="h", code_uri="s3://b/k.zip"), "Topic": sns.topic(), **sam.connect("C", "F", "Topic", ["Read"])})
    with pytest.raises(NotImplementedError, match="Read on AWS::SNS::Topic"):
        sam.expand(tpl)


@pytest.mark.parametrize("event", [
    sam.sns_event(ref("Topic")),
    sam.stream_event("Kinesis", get_att("Stream", "Arn"), batch_size=5),
    sam.stream_event("DynamoDB", get_att("Ddb", "StreamArn"), starting_position="TRIM_HORIZON"),
    sam.event_bridge_event({"source": ["a.b"]}),
    sam.sqs_event(get_att("Q", "Arn"), batch_size=3),
], ids=["sns", "kinesis", "dynamodb", "eventbridge", "sqs"])
def test_more_events_expand_to_what_sam_makes(event: Any) -> None:
    tpl = sam.template({
        "Topic": sns.topic(), "Q": sqs.queue(), "Stream": kinesis.stream(ShardCount=1), "Ddb": dynamodb.table(KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}]),
        "F": sam.function(handler="h", code_uri="s3://b/k.zip", runtime="python3.12", events={"E": event}),
    })
    ours, theirs = sam.expand(tpl)["Resources"], translate(tpl)
    for logical in ("F", "FRole", "FE", "FEPermission"):
        if logical in theirs:
            assert logical in ours, f"{logical}: logical IDs must match SAM's"
            assert normal(ours[logical]) == normal(theirs[logical])
    assert_template_ok(sam.expand(tpl))


def test_a_polling_event_without_its_source_is_a_clear_error() -> None:
    bad = {"Resources": {"F": {"Type": "AWS::Serverless::Function", "Properties": {"Handler": "h", "CodeUri": "s3://b/k", "Events": {"K": {"Type": "Kinesis", "Properties": {}}}}}}}
    with pytest.raises(NotImplementedError, match="Stream"):
        sam.expand(bad)  # ty: ignore[invalid-argument-type]


def test_embedded_connectors_are_a_policy_on_the_function_role() -> None:
    tpl = sam.template({
        "Q": sqs.queue(),
        "F": serverless.function(Handler="h", Runtime="python3.12", CodeUri="s3://b/k.zip", connectors={"ToQ": {"Properties": {"Destination": {"Id": "Q"}, "Permissions": ["Read", "Write"]}}}),
    })
    ours, theirs = sam.expand(tpl)["Resources"], translate(tpl)
    theirs["FToQPolicy"].pop("Metadata")
    assert normal(ours["FToQPolicy"]) == normal(theirs["FToQPolicy"])


def test_state_machine_matches_sam() -> None:
    nightly: Any = {"Type": "Schedule", "Properties": {"Schedule": "rate(1 day)"}}  # an inline union of event types is beyond the checker
    tpl = sam.template({
        "F": sam.function(handler="h", code_uri="s3://b/k.zip", runtime="python3.12"),
        "SM": serverless.state_machine(
            Definition={"StartAt": "A", "States": {"A": {"Type": "Task", "Resource": "${Fn}", "End": True}}},
            DefinitionSubstitutions={"Fn": get_att("F", "Arn")},
            Policies=[{"Statement": [{"Effect": "Allow", "Action": "lambda:InvokeFunction", "Resource": "*"}]}],
            Events={"Nightly": nightly},
        ),
    })
    ours, theirs = sam.expand(tpl)["Resources"], translate(tpl)
    for logical in ("SM", "SMRole", "SMNightly", "SMNightlyRole"):
        assert normal(ours[logical]) == normal(theirs[logical]), logical
    assert "SAM" not in json.dumps(sam.expand(tpl))
    assert_template_ok(sam.expand(tpl))


def test_rest_api_events_become_plain_apigateway_v1_resources() -> None:
    tpl = sam.template({"Web": sam.function(handler="h", code_uri="s3://b/k.zip", events={
        "List": sam.api_event("/orders", "get"), "One": sam.api_event("/orders/{id}", "GET"), "Root": sam.api_event("/", "GET")})})
    out = sam.expand(tpl)["Resources"]
    kinds = [r["Type"] for r in out.values()]
    assert kinds.count("AWS::ApiGateway::Method") == 3 and kinds.count("AWS::ApiGateway::Resource") == 2
    parts = {r["Properties"]["PathPart"] for r in out.values() if r["Type"] == "AWS::ApiGateway::Resource"}
    assert parts == {"orders", "{id}"}  # `/orders/{id}` hangs under `/orders`, one resource per segment
    assert "Body" not in json.dumps(out) and "openapi" not in json.dumps(out)
    deployments = [k for k, r in out.items() if r["Type"] == "AWS::ApiGateway::Deployment"]
    assert len(deployments) == 1
    other = sam.expand(sam.template({"Web": sam.function(handler="h", code_uri="s3://b/k.zip", events={"List": sam.api_event("/orders", "get")})}))
    assert [k for k, r in other["Resources"].items() if r["Type"] == "AWS::ApiGateway::Deployment"] != deployments  # new routes, new deployment
    assert_template_ok(sam.expand(tpl))
