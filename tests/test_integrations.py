import json
import sys
from pathlib import Path
from collections.abc import Mapping
from typing import Any, cast

sys.path.insert(0, str(Path(__file__).parent.parent / "examples"))

import cfn_types  # noqa: E402
import pytest  # noqa: E402
from cfn_types import dynamodb, lambda_, sns, sqs
from cfn_types import elasticloadbalancingv2 as elbv2  # noqa: E402
from constructs import topic_to_queue  # noqa: E402
from integrations import (  # noqa: E402
    alias_to_distribution, alias_to_load_balancer, api_to_dynamodb, api_to_lambda, bucket_to_lambda, event_to_lambda,
    event_to_queue, fan_out, fargate_task, firehose_to_s3, lambda_behind_alb, static_site, stream_trigger,
    with_stream,
)

from cfn_typed import Resources, combine, get_att, ref  # noqa: E402
from cfn_typed.testing import assert_references_resolve, assert_template_ok  # noqa: E402


def plain(value: Any) -> Any:
    return json.loads(json.dumps(value))


def template(*fragments: Mapping[str, Any]) -> dict[str, Any]:
    return {"Resources": plain(combine(*(cast(Resources, f) for f in fragments)))}


FN: Resources = {"Fn": lambda_.function(Code={"ZipFile": "x"}, Role="arn:aws:iam::123456789012:role/fn", Runtime="python3.13", Handler="i.h")}
ORDERS = dynamodb.table(
    AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}],
    KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}],
    BillingMode="PAY_PER_REQUEST",
)
TABLE: Resources = {"Table": ORDERS}
QUEUE: Resources = {"Queue": sqs.queue()}


def test_static_site_is_private_and_readable_only_by_its_distribution() -> None:
    t = template(static_site("Site"))
    assert set(t["Resources"]) == {"SiteBucket", "SiteOAC", "SiteDistribution", "SiteBucketPolicy"}
    origin = t["Resources"]["SiteDistribution"]["Properties"]["DistributionConfig"]["Origins"][0]
    assert origin["OriginAccessControlId"] == {"Fn::GetAtt": ["SiteOAC", "Id"]}
    statement = t["Resources"]["SiteBucketPolicy"]["Properties"]["PolicyDocument"]["Statement"][0]
    assert statement["Principal"] == {"Service": "cloudfront.amazonaws.com"}
    assert "aws:SourceArn" in statement["Condition"]["ArnEquals"]
    assert_references_resolve(t)


def test_api_to_lambda_deploys_after_its_methods_and_may_invoke() -> None:
    frag = api_to_lambda("Web", "Fn")
    t = template(FN, frag)
    assert t["Resources"]["WebDeployment"]["DependsOn"] == ["WebProxyMethod", "WebRootMethod"]
    permission = t["Resources"]["WebInvokePermission"]["Properties"]
    assert permission["Principal"] == "apigateway.amazonaws.com" and permission["FunctionName"] == {"Ref": "Fn"}
    assert t["Resources"]["WebProxy"]["Properties"]["PathPart"] == "{proxy+}"
    assert_references_resolve(t)


def test_api_to_dynamodb_reads_only_the_table_through_a_role() -> None:
    t = template(TABLE, api_to_dynamodb("Items", "Table"))
    policy = t["Resources"]["ItemsRole"]["Properties"]["Policies"][0]["PolicyDocument"]["Statement"][0]
    assert policy["Action"] == "dynamodb:GetItem" and policy["Resource"] == {"Fn::GetAtt": ["Table", "Arn"]}
    integration = t["Resources"]["ItemsGetMethod"]["Properties"]["Integration"]
    assert integration["Type"] == "AWS" and "GetItem" in integration["Uri"]["Fn::Sub"]
    template_text, variables = integration["RequestTemplates"]["application/json"]["Fn::Sub"]
    assert variables == {"T": {"Ref": "Table"}} and '"pk"' in template_text
    assert_references_resolve(t)


def test_alb_lambda_target_group_waits_for_the_permission() -> None:
    listener = {"Listener": {"Type": "AWS::ElasticLoadBalancingV2::Listener", "Properties": {}}}
    t = template(FN, lambda_behind_alb("Api", "Fn", listener="Listener", target_group_name="api-fn", path_pattern="/api/*", priority=10))
    t["Resources"].update(plain(listener))
    assert t["Resources"]["ApiTargetGroup"]["DependsOn"] == "ApiInvokePermission"
    source = t["Resources"]["ApiInvokePermission"]["Properties"]["SourceArn"]["Fn::Sub"]
    assert source.endswith(":targetgroup/api-fn/*") and "ApiTargetGroup" not in source  # naming the group by Ref is a cycle
    assert t["Resources"]["ApiRule"]["Properties"]["Priority"] == 10
    assert_references_resolve(t)


def test_route53_aliases() -> None:
    lb = alias_to_load_balancer("Dns", zone_id="Z1", record="a.example.com", load_balancer="LB")["Dns"]["Properties"]
    assert lb["AliasTarget"]["HostedZoneId"] == get_att("LB", "CanonicalHostedZoneID")
    cf = alias_to_distribution("Dns", zone_id="Z1", record="a.example.com", distribution="D")["Dns"]["Properties"]
    assert cf["AliasTarget"]["HostedZoneId"] == "Z2FDTNDATAQYW2" and cf["AliasTarget"]["DNSName"] == get_att("D", "DomainName")


def test_topic_to_queue_lets_only_that_topic_send() -> None:
    t = template({"Topic": sns.topic()}, QUEUE, topic_to_queue("Queue", ["Topic"]))
    statement = t["Resources"]["QueuePolicy"]["Properties"]["PolicyDocument"]["Statement"][0]
    assert statement["Condition"] == {"ArnEquals": {"aws:SourceArn": [{"Ref": "Topic"}]}}
    assert t["Resources"]["QueueTopicSubscription"]["Properties"]["RawMessageDelivery"] is False
    assert_references_resolve(t)


def test_fan_out_gives_each_subscriber_a_queue_pair() -> None:
    t = template(fan_out("Orders", ["Billing", "Shipping"]))
    assert set(t["Resources"]) == {
        "OrdersTopic",
        *(f"{s}{x}" for s in ("Billing", "Shipping") for x in ("Queue", "DLQ", "QueuePolicy", "QueueOrdersTopicSubscription")),
    }
    assert_references_resolve(t)


def test_event_rules_need_exactly_one_trigger_and_grant_the_target() -> None:
    t = template(FN, event_to_lambda("Tick", "Fn", schedule="rate(5 minutes)"))
    assert t["Resources"]["TickInvokePermission"]["Properties"]["SourceArn"] == {"Fn::GetAtt": ["TickRule", "Arn"]}
    assert_references_resolve(t)
    q = template(QUEUE, event_to_queue("Created", "Queue", pattern={"source": ["app"]}))
    assert q["Resources"]["CreatedRule"]["Properties"]["EventPattern"] == {"source": ["app"]}
    assert_references_resolve(q)
    with pytest.raises(ValueError, match="exactly one"):
        event_to_lambda("X", "Fn")
    with pytest.raises(ValueError, match="exactly one"):
        event_to_queue("X", "Queue", pattern={}, schedule="rate(1 minute)")


def test_stream_trigger_reads_the_stream_and_the_table_has_one() -> None:
    plain_table = ORDERS
    streamed = with_stream(plain_table, "NEW_IMAGE")
    assert "StreamSpecification" not in plain_table["Properties"]
    assert streamed["Properties"]["StreamSpecification"] == {"StreamViewType": "NEW_IMAGE"}
    trigger = stream_trigger("Changes", "Fn", "Table", batch_size=50)
    props = plain(trigger.resources["ChangesStreamMapping"])["Properties"]
    assert props["EventSourceArn"] == {"Fn::GetAtt": ["Table", "StreamArn"]}
    assert props["BisectBatchOnFunctionError"] is True and props["BatchSize"] == 50
    assert plain(trigger.statements[0])["Action"] == ["dynamodb:DescribeStream", "dynamodb:GetRecords", "dynamodb:GetShardIterator"]
    assert_references_resolve(template(FN, {"Table": streamed}, trigger.resources))


def test_bucket_to_lambda_avoids_the_circular_dependency() -> None:
    t = template(FN, bucket_to_lambda("Uploads", "Fn", bucket_name="acme-uploads", prefix="in/", suffix=".csv"))
    bucket = t["Resources"]["UploadsBucket"]
    assert bucket["DependsOn"] == "UploadsInvokePermission"
    assert "UploadsBucket" not in json.dumps(t["Resources"]["UploadsInvokePermission"])  # no GetAtt back to the bucket
    config = bucket["Properties"]["NotificationConfiguration"]["LambdaConfigurations"][0]
    assert config["Filter"]["S3Key"]["Rules"] == [{"Name": "prefix", "Value": "in/"}, {"Name": "suffix", "Value": ".csv"}]
    assert_references_resolve(t)


def test_firehose_role_writes_only_to_its_bucket_and_logs() -> None:
    t = template(firehose_to_s3("Events", bucket_arn="arn:aws:s3:::lake"))
    assert t["Resources"]["EventsStream"]["DependsOn"] == "EventsLogStream"
    statements = t["Resources"]["EventsRole"]["Properties"]["Policies"][0]["PolicyDocument"]["Statement"]
    assert statements[0]["Resource"] == "arn:aws:s3:::lake" and statements[-1]["Action"] == "logs:PutLogEvents"
    assert_references_resolve(t)


def test_fargate_task_separates_execution_and_task_roles() -> None:
    from cfn_typed import allow

    svc = fargate_task(
        "Worker", image="img", subnets=ref("Subnets"), security_groups=[ref("Sg")], environment={"A": "1"},
        task_statements=[allow("sqs:ReceiveMessage", "*")],
    )
    t = template(svc.resources)
    task = t["Resources"]["WorkerTask"]["Properties"]
    assert task["ExecutionRoleArn"] != task["TaskRoleArn"]
    assert "Policies" in t["Resources"]["WorkerTaskRole"]["Properties"]
    assert "Policies" not in t["Resources"]["WorkerExecutionRole"]["Properties"]
    assert t["Resources"]["WorkerService"]["Properties"]["DeploymentConfiguration"]["DeploymentCircuitBreaker"]["Rollback"] is True
    assert plain(svc.run_task_statements[1])["Resource"] == [
        {"Fn::GetAtt": ["WorkerExecutionRole", "Arn"]}, {"Fn::GetAtt": ["WorkerTaskRole", "Arn"]},
    ]
    assert set(svc.environment) == {"CLUSTER_ARN", "TASK_DEFINITION_ARN", "SUBNETS", "SECURITY_GROUPS"}


def test_a_task_that_is_only_run_on_demand_has_no_service() -> None:
    svc = fargate_task("Job", image="img", subnets=ref("Subnets"), security_groups=[ref("Sg")], desired_count=None)
    assert "JobService" not in svc.resources


PARAMS: dict[str, Any] = {
    "Subnets": {"Type": "List<AWS::EC2::Subnet::Id>"},
    "Sg": {"Type": "AWS::EC2::SecurityGroup::Id"},
    "Zone": {"Type": "AWS::Route53::HostedZone::Id"},
}
LISTENER: Resources = {"Listener": elbv2.listener(
    LoadBalancerArn="arn:aws:elasticloadbalancing:eu-west-1:123456789012:loadbalancer/app/lb/50dc6c495c0c9188",
    Port=80, Protocol="HTTP", DefaultActions=[{"Type": "fixed-response", "FixedResponseConfig": {"StatusCode": "404"}}],
)}
LB: Resources = {"LB": elbv2.load_balancer(Subnets=ref("Subnets"))}
STREAMED: Resources = {"Table": with_stream(ORDERS)}
SITE = static_site("Site")

# Each pattern with only the resources it refers to, so the built-in checks run on it alone and a failure names it.
CASES: dict[str, tuple[Resources, ...]] = {
    "static_site": (SITE,),
    "api_to_lambda": (FN, api_to_lambda("Web", "Fn")),
    "api_to_dynamodb": (TABLE, api_to_dynamodb("Items", "Table")),
    "lambda_behind_alb": (FN, LISTENER, lambda_behind_alb("Api", "Fn", listener="Listener", target_group_name="api-fn", path_pattern="/api/*", priority=10)),
    "alias_to_load_balancer": (LB, alias_to_load_balancer("Dns", zone_id=ref("Zone"), record="a.example.com", load_balancer="LB")),
    "alias_to_distribution": (SITE, alias_to_distribution("Dns", zone_id=ref("Zone"), record="b.example.com", distribution="SiteDistribution")),
    "fan_out": (fan_out("Orders", ["Billing", "Shipping"]),),
    "event_to_lambda": (FN, event_to_lambda("Tick", "Fn", schedule="rate(5 minutes)")),
    "event_to_lambda_pattern": (FN, event_to_lambda("Seen", "Fn", pattern={"source": ["app"]})),
    "event_to_queue": (QUEUE, event_to_queue("Created", "Queue", pattern={"source": ["app"]})),
    "stream_trigger": (FN, STREAMED, stream_trigger("Changes", "Fn", "Table").resources),
    "bucket_to_lambda": (FN, bucket_to_lambda("Uploads", "Fn", bucket_name="acme-uploads", prefix="in/", suffix=".csv")),
    "firehose_to_s3": (firehose_to_s3("Events", bucket_arn="arn:aws:s3:::lake"),),
    "fargate_task": (fargate_task("Worker", image="img", subnets=ref("Subnets"), security_groups=[ref("Sg")]).resources,),
    "fargate_task_on_demand": (fargate_task("Job", image="img", subnets=ref("Subnets"), security_groups=[ref("Sg")], desired_count=None).resources,),
}


@pytest.mark.parametrize("fragments", CASES.values(), ids=CASES.keys())
def test_each_pattern_passes_the_built_in_checks_on_its_own(fragments: tuple[Resources, ...]) -> None:
    """References, constraints, attribute names, property combinations, IAM, runtimes and limits, per pattern."""
    t = template(*fragments)
    t["Parameters"] = PARAMS
    assert_template_ok(t, cfn_types, unused=False)
