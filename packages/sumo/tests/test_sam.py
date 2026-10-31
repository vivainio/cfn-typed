from typing import Any

from cfn_typed import get_att, ref
from cfn_typed.testing import assert_template_ok

from cfn_typed_sumo import sam
from cfn_typed_sumo.types import serverless


def test_sam_template_has_the_transform_and_globals() -> None:
    fn = serverless.function(
        Handler="app.handler", CodeUri="src/",
        Events={"Orders": sam.sqs_event(get_att("Queue", "Arn"), max_batching_window=5), "Web": sam.http_api_event("/orders", "POST")},
    )
    tpl = sam.template({"Worker": fn}, function_globals={"Runtime": "python3.12", "Timeout": 30})
    assert tpl["Transform"] == "AWS::Serverless-2016-10-31"
    assert tpl["Globals"] == {"Function": {"Runtime": "python3.12", "Timeout": 30}}
    assert tpl["Resources"]["Worker"]["Properties"]["Events"]["Orders"] == {
        "Type": "SQS", "Properties": {"Queue": get_att("Queue", "Arn"), "BatchSize": 10, "MaximumBatchingWindowInSeconds": 5},
    }


def test_globals_merge_and_are_omitted_when_empty() -> None:
    assert "Globals" not in sam.template({})
    tpl = sam.template({}, globals={"Function": {"Timeout": 5}, "Api": {"Cors": "*"}}, function_globals={"Runtime": "python3.12"})
    assert tpl["Globals"] == {"Function": {"Timeout": 5, "Runtime": "python3.12"}, "Api": {"Cors": "*"}}


def test_schedule_event_and_simple_table_render() -> None:
    tpl = sam.template({
        "Cleanup": serverless.function(Handler="app.run", Runtime="python3.12", CodeUri="src/", Events={"Nightly": sam.schedule_event("cron(0 3 * * ? *)")}),
        "Table": serverless.simple_table(),
    })
    assert tpl["Resources"]["Table"] == {"Type": "AWS::Serverless::SimpleTable"}
    assert tpl["Resources"]["Cleanup"]["Properties"]["Events"]["Nightly"]["Type"] == "Schedule"
    assert_template_ok(tpl)


def test_function_pattern_builds_events_environment_and_policies() -> None:
    from cfn_typed import allow

    fn = sam.function(
        handler="app.handler", code_uri="src/", timeout=30,
        events={"Orders": sam.sqs_event(get_att("Queue", "Arn"))},
        environment={"TABLE": ref("Table")},
        statements=[allow("dynamodb:GetItem", get_att("Table", "Arn"))],
        managed_policies=["AWSLambdaBasicExecutionRole"],
    )
    props: Any = fn["Properties"]
    assert props["Handler"] == "app.handler" and props["Timeout"] == 30
    assert "Runtime" not in props and "MemorySize" not in props  # left to Globals
    assert props["Environment"] == {"Variables": {"TABLE": ref("Table")}}
    assert props["Policies"][0] == "AWSLambdaBasicExecutionRole"
    assert props["Policies"][1]["Statement"][0]["Action"] == ["dynamodb:GetItem"] or props["Policies"][1]["Statement"][0]["Action"] == "dynamodb:GetItem"
    assert "Events" not in sam.function(handler="h", code_uri="s")["Properties"]


def test_table_and_connect() -> None:
    assert sam.table("pk")["Properties"] == {"PrimaryKey": {"Name": "pk", "Type": "String"}}
    one = sam.connect("Worker", "Worker", "Table", ["Read", "Write"])["WorkerConnector"]["Properties"]
    assert one == {"Source": {"Id": "Worker"}, "Destination": {"Id": "Table"}, "Permissions": ["Read", "Write"]}
    many = sam.connect("W", "Worker", ["A", "B"])["WConnector"]["Properties"]
    assert many["Destination"] == [{"Id": "A"}, {"Id": "B"}]
    assert_template_ok(sam.template({"Table": sam.table("pk"), **sam.connect("W", "Worker", "Table")}))
