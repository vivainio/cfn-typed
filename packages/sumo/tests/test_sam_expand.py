"""`sam.expand` against AWS's own SAM translator (the dev dependency `aws-sam-translator`, same release as the types)."""

import copy
import json
import re
from typing import Any

import pytest
from cfn_typed import allow, get_att
from cfn_typed.testing import assert_template_ok

from cfn_typed_sumo import sam
from cfn_typed_sumo.types import serverless, sqs


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
        out = {k: normal(v) for k, v in value.items() if k != "Version" or "Statement" not in value}
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
    with pytest.raises(NotImplementedError, match="Connectors"):
        sam.expand(sam.template({"F": serverless.function(Handler="h", CodeUri="s3://b/k.zip", connectors={"x": {}})}))
    with pytest.raises(NotImplementedError, match="AWS::Serverless::StateMachine"):
        sam.expand({"Resources": {"S": {"Type": "AWS::Serverless::StateMachine", "Properties": {}}}})
    with pytest.raises(NotImplementedError, match="Tracing"):
        sam.expand({"Resources": {"F": {"Type": "AWS::Serverless::Function", "Properties": {"Handler": "h", "CodeUri": "s3://b/k", "Tracing": "Active"}}}})
    with pytest.raises(NotImplementedError, match="Kinesis"):
        sam.expand({"Resources": {"F": {"Type": "AWS::Serverless::Function", "Properties": {"Handler": "h", "CodeUri": "s3://b/k", "Events": {"K": {"Type": "Kinesis", "Properties": {}}}}}}})


def test_other_resources_and_template_keys_pass_through() -> None:
    tpl = sam.template({"Orders": sqs.queue()}, description="d")
    out = sam.expand(tpl)
    assert out["Resources"] == tpl["Resources"] and out["Description"] == "d"
    assert re.fullmatch(r"\d{4}-\d\d-\d\d", out["AWSTemplateFormatVersion"])
