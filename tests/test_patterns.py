import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "examples"))

from patterns import combine, lambda_role, queue_with_dlq, sqs_event_source  # noqa: E402

from cfn_typed import get_att, tags  # noqa: E402


def test_queue_with_dlq_is_a_fragment() -> None:
    frag = queue_with_dlq("Order", visibility_timeout=180, tags=tags(Stage="dev"))
    assert set(frag) == {"OrderQueue", "OrderDLQ"}
    props = frag["OrderQueue"]["Properties"]
    assert props["VisibilityTimeout"] == 180
    assert props["RedrivePolicy"]["deadLetterTargetArn"] == get_att("OrderDLQ", "Arn")
    assert "Tags" not in queue_with_dlq("X")["XDLQ"]


def test_single_resource_helpers() -> None:
    assert lambda_role("svc", [])["Type"] == "AWS::IAM::Role"
    assert sqs_event_source("Fn", get_att("Q", "Arn"))["Properties"]["BatchSize"] == 10


def test_combine_rejects_duplicates() -> None:
    assert set(combine(queue_with_dlq("A"), queue_with_dlq("B"))) == {"AQueue", "ADLQ", "BQueue", "BDLQ"}
    with pytest.raises(ValueError, match="AQueue"):
        combine(queue_with_dlq("A"), queue_with_dlq("A"))
