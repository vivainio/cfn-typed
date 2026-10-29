import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "examples"))

from patterns import lambda_role, queue_with_dlq, sqs_event_source  # noqa: E402

from cfn_typed import get_att, ref, tags  # noqa: E402


def test_queue_with_dlq_is_a_fragment() -> None:
    orders = queue_with_dlq("Order", visibility_timeout=180, tags=tags(Stage="dev"))
    frag = orders.resources
    assert set(frag) == {"OrderQueue", "OrderDLQ"}
    assert (orders.queue, orders.dlq) == ("OrderQueue", "OrderDLQ")
    assert orders.queue_arn == get_att("OrderQueue", "Arn")
    assert orders.queue_url == ref("OrderQueue")
    props = frag["OrderQueue"]["Properties"]
    assert props["VisibilityTimeout"] == 180
    assert props["RedrivePolicy"]["deadLetterTargetArn"] == get_att("OrderDLQ", "Arn")
    assert "Tags" not in queue_with_dlq("X").resources["XDLQ"]


def test_single_resource_helpers() -> None:
    assert lambda_role("svc", [])["Type"] == "AWS::IAM::Role"
    assert sqs_event_source("Fn", get_att("Q", "Arn"))["Properties"]["BatchSize"] == 10

