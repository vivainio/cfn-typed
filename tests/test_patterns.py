from cfn_typed import get_att, tags
from cfn_typed.patterns import lambda_role, queue_with_dlq, sqs_event_source


def test_queue_with_dlq_is_a_fragment() -> None:
    frag = queue_with_dlq("Order", visibility_timeout=180, tags=tags(Stage="dev"))
    assert set(frag) == {"OrderQueue", "OrderDLQ"}
    props = frag["OrderQueue"]["Properties"]
    assert props["VisibilityTimeout"] == 180
    assert props["RedrivePolicy"]["deadLetterTargetArn"] == get_att("OrderDLQ", "Arn")
    assert "Tags" not in queue_with_dlq("X")["XDLQ"]


def test_single_resource_helpers() -> None:
    assert lambda_role("svc", [])["Type"] == "AWS::IAM::Role"
    mapping = sqs_event_source("Fn", get_att("Q", "Arn"))
    assert mapping["Properties"]["BatchSize"] == 10
