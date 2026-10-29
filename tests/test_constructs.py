import json
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "examples"))

from constructs import (
    alarm, alarm_topic, composite_alarm, fargate_service, function, lambda_errors_alarm, lambda_scaling, live_alias,
    queue_backlog_alarm, queue_step_scaling, schedule, service_scaling, table_scaling, topic_to_queue, vpc,
)  # noqa: E402
from cfn_types import lambda_  # noqa: E402

import cfn_typed as cfn  # noqa: E402

CODE = lambda_.FunctionCode(ZipFile="def handler(e, c): pass")


def plain(value: Any) -> Any:
    return json.loads(json.dumps(value))


def test_function_comes_with_role_and_a_log_group_that_expires() -> None:
    fn = function("Job", code=CODE, handler="index.handler", runtime="python3.13", statements=[cfn.allow("s3:GetObject", "*")])
    res = plain(fn.resources)
    assert set(res) == {"Job", "JobRole", "JobLogs"}
    assert res["JobLogs"]["Properties"]["RetentionInDays"] == 30
    assert res["Job"]["Properties"]["LoggingConfig"] == {"LogGroup": {"Ref": "JobLogs"}}
    assert res["JobRole"]["Properties"]["Policies"][0]["PolicyName"] == "Job-inline"
    assert "Policies" not in plain(function("B", code=CODE, handler="h", runtime="r").resources["BRole"])["Properties"]


def test_schedule_always_brings_the_permission() -> None:
    res = plain(schedule("Nightly", "rate(1 day)", "Job"))
    assert set(res) == {"NightlyRule", "NightlyPermission"}
    assert res["NightlyPermission"]["Properties"]["SourceArn"] == {"Fn::GetAtt": ["NightlyRule", "Arn"]}


def test_one_queue_policy_covers_all_topics() -> None:
    res = plain(topic_to_queue("Work", ["Orders", "Refunds"]))
    assert set(res) == {"WorkPolicy", "WorkOrdersSubscription", "WorkRefundsSubscription"}
    cond = res["WorkPolicy"]["Properties"]["PolicyDocument"]["Statement"][0]["Condition"]
    assert cond == {"ArnEquals": {"aws:SourceArn": [{"Ref": "Orders"}, {"Ref": "Refunds"}]}}
    assert res["WorkOrdersSubscription"]["Properties"]["Protocol"] == "sqs"


def test_vpc_has_a_subnet_pair_and_a_nat_per_zone() -> None:
    net = vpc("Net", zones=3)
    assert net.public == ["NetPublic1", "NetPublic2", "NetPublic3"]
    kinds = [r["Type"] for r in net.resources.values()]
    assert kinds.count("AWS::EC2::NatGateway") == 3 and kinds.count("AWS::EC2::Subnet") == 6
    no_nat = [r["Type"] for r in vpc("Net", nat_gateways=False).resources.values()]
    assert "AWS::EC2::NatGateway" not in no_nat and "AWS::EC2::EIP" not in no_nat
    assert len(set(plain(r["Properties"]["CidrBlock"])["Fn::Select"][0] for r in net.resources.values() if r["Type"] == "AWS::EC2::Subnet")) == 6  # no two subnets share a block


def test_fargate_service_wires_the_service_to_the_target_group_after_the_listener() -> None:
    net = vpc("Net")
    svc = fargate_service("Web", vpc_id=net.vpc_id, public_subnets=net.public_subnet_ids, private_subnets=net.private_subnet_ids, image="nginx")
    res = plain(svc.resources)
    assert res["WebService"]["DependsOn"] == "WebListener"
    assert res["WebTargetGroup"]["Properties"]["TargetType"] == "ip"
    assert res["WebService"]["Properties"]["LoadBalancers"][0]["TargetGroupArn"] == {"Ref": "WebTargetGroup"}
    assert res["WebService"]["Properties"]["NetworkConfiguration"]["AwsvpcConfiguration"]["AssignPublicIp"] == "DISABLED"
    cfn.combine(net, svc)  # no clashing logical IDs


def test_alarm_notifies_on_recovery_only_when_asked() -> None:
    topic = [cfn.ref("Alerts")]
    both = plain(queue_backlog_alarm("Orders", threshold=100, actions=topic))["Properties"]
    assert both["AlarmActions"] == both["OKActions"] == [{"Ref": "Alerts"}]
    assert both["Dimensions"] == [{"Name": "QueueName", "Value": {"Fn::GetAtt": ["Orders", "QueueName"]}}]
    only = plain(alarm("AWS/X", "M", dimensions={}, threshold=1, actions=topic))["Properties"]
    assert "OKActions" not in only and "AlarmDescription" not in only
    assert "AlarmActions" not in plain(lambda_errors_alarm("Job"))["Properties"]


def test_alarm_topic_subscribes_each_address() -> None:
    res = plain(alarm_topic("Ops", ["a@example.com", "b@example.com"]))
    assert set(res) == {"OpsTopic", "OpsEmail1", "OpsEmail2"}
    assert res["OpsEmail2"]["Properties"] == {"TopicArn": {"Ref": "OpsTopic"}, "Protocol": "email", "Endpoint": "b@example.com"}


def test_service_scaling_tracks_what_it_is_given() -> None:
    res = plain(service_scaling("Web", cluster="WebCluster", service="WebService", min_capacity=2, max_capacity=10, cpu_percent=60))
    assert set(res) == {"WebTarget", "WebCpu"}
    assert res["WebTarget"]["Properties"]["ResourceId"] == {"Fn::Sub": "service/${WebCluster}/${WebService.Name}"}
    config = res["WebCpu"]["Properties"]["TargetTrackingScalingPolicyConfiguration"]
    assert config["PredefinedMetricSpecification"]["PredefinedMetricType"] == "ECSServiceAverageCPUUtilization"
    assert config["ScaleInCooldown"] > config["ScaleOutCooldown"]
    with pytest.raises(ValueError):
        service_scaling("W", cluster="C", service="S", min_capacity=1, max_capacity=2)


def test_queue_steps_are_relative_to_the_alarm_threshold_and_scaling_alarms_do_not_fire_on_ok() -> None:
    res = plain(queue_step_scaling("Work", cluster="C", service="S", queue="Q", min_capacity=1, max_capacity=20,
                                   steps=[(10, 1), (100, 3), (500, 10)]))
    assert set(res) == {"WorkTarget", "WorkOut", "WorkOutAlarm", "WorkIn", "WorkInAlarm"}
    steps = res["WorkOut"]["Properties"]["StepScalingPolicyConfiguration"]["StepAdjustments"]
    assert steps == [
        {"MetricIntervalLowerBound": 0, "MetricIntervalUpperBound": 90, "ScalingAdjustment": 1},
        {"MetricIntervalLowerBound": 90, "MetricIntervalUpperBound": 490, "ScalingAdjustment": 3},
        {"MetricIntervalLowerBound": 490, "ScalingAdjustment": 10},
    ]
    out_alarm = res["WorkOutAlarm"]["Properties"]
    assert out_alarm["Threshold"] == 10 and out_alarm["AlarmActions"] == [{"Ref": "WorkOut"}]
    assert "OKActions" not in out_alarm and "OKActions" not in res["WorkInAlarm"]["Properties"]
    assert res["WorkInAlarm"]["Properties"]["ComparisonOperator"] == "LessThanOrEqualToThreshold"


def test_composite_alarm_joins_the_alarms_by_arn() -> None:
    both = plain(composite_alarm("Page", ["Backlog", "Errors"], actions=[cfn.ref("Alerts")]))["Properties"]
    assert both["AlarmRule"] == {"Fn::Join": [" AND ", [{"Fn::Sub": "ALARM(${Backlog.Arn})"}, {"Fn::Sub": "ALARM(${Errors.Arn})"}]]}
    assert both["AlarmActions"] == both["OKActions"]
    assert plain(composite_alarm("P", ["A", "B"], when="any"))["Properties"]["AlarmRule"]["Fn::Join"][0] == " OR "


def test_requests_per_target_is_labelled_with_the_full_names() -> None:
    res = plain(service_scaling("Web", cluster="C", service="S", min_capacity=1, max_capacity=4,
                                requests_per_target=("WebLoadBalancer", "WebTargetGroup", 1000)))
    assert set(res) == {"WebTarget", "WebRequests"}
    config = res["WebRequests"]["Properties"]["TargetTrackingScalingPolicyConfiguration"]
    assert config["TargetValue"] == 1000
    assert config["PredefinedMetricSpecification"] == {
        "PredefinedMetricType": "ALBRequestCountPerTarget",
        "ResourceLabel": {"Fn::Sub": "${WebLoadBalancer.LoadBalancerFullName}/${WebTargetGroup.TargetGroupFullName}"},
    }


def test_a_new_version_needs_a_new_logical_id() -> None:
    assert set(live_alias("Job", "JobFn")) == {"JobVersion1", "JobAlias"}
    res = plain(live_alias("Job", "JobFn", version="2", provisioned=3))
    assert set(res) == {"JobVersion2", "JobAlias"}
    assert res["JobAlias"]["Properties"]["ProvisionedConcurrencyConfig"] == {"ProvisionedConcurrentExecutions": 3}


def test_lambda_scaling_targets_the_alias_after_it_exists() -> None:
    res = plain(lambda_scaling("Job", function_logical="JobFn", alias_logical="JobAlias", min_capacity=1, max_capacity=10))
    assert res["JobTarget"]["DependsOn"] == "JobAlias"
    assert res["JobTarget"]["Properties"]["ResourceId"] == {"Fn::Sub": "function:${JobFn}:live"}


def test_table_scaling_registers_only_what_is_given() -> None:
    res = plain(table_scaling("Orders", table="OrdersTable", write=(5, 100)))
    assert set(res) == {"OrdersWriteTarget", "OrdersWriteTracking"}
    assert res["OrdersWriteTarget"]["Properties"]["ScalableDimension"] == "dynamodb:table:WriteCapacityUnits"
    both = table_scaling("Orders", table="OrdersTable", read=(5, 50), write=(5, 100))
    assert len(both) == 4
