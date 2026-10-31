import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "examples"))

from patterns import CompanyTags, SomeCompanyTags, lambda_role, queue_with_dlq, sqs_event_source, tagged, untagged  # noqa: E402

import pytest  # noqa: E402

from cfn_typed import Resources, get_att, ref, tags  # noqa: E402


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



SERVICE: SomeCompanyTags = {"owner": "team-a", "cost_center": "CC-1234", "environment": "prod", "role": "queue"}


def test_company_tags_are_mandatory_and_validated() -> None:
    with pytest.raises(TypeError):
        CompanyTags(owner="team-a", environment="prod", role="x")  # ty: ignore[missing-argument]
    with pytest.raises(ValueError, match="cost_center"):
        CompanyTags(owner="team-a", cost_center="42", environment="prod", role="x")


def tags_of(frag: Resources, logical_id: str) -> dict[str, str]:
    return {t["Key"]: t["Value"] for t in frag[logical_id]["Properties"]["Tags"]}


def test_service_tags_apply_and_a_resource_overrides_some() -> None:
    frag = {
        "Role": lambda_role("svc", []),
        "Q": queue_with_dlq("Order").resources["OrderQueue"],
        "DLQ": queue_with_dlq("Order", tags=tags(role="dlq", Extra="1")).resources["OrderDLQ"],
    }
    assert untagged(frag) == ["Q", "DLQ"]
    out = tagged(frag, SERVICE)
    assert untagged(out) == []
    assert tags_of(out, "Q") == SERVICE
    assert tags_of(out, "DLQ") == {**SERVICE, "role": "dlq", "Extra": "1"}
    assert "Tags" not in out["Role"].get("Properties", {})


def test_tagged_refuses_incomplete_or_invalid_tags() -> None:
    frag = queue_with_dlq("Order").resources
    partial: SomeCompanyTags = {"owner": "team-a"}
    with pytest.raises(ValueError, match="OrderDLQ is missing company tags: cost_center, environment, role"):
        tagged(frag, partial)
    tagged(frag, partial | {"cost_center": "CC-1234", "environment": "dev"} | {"role": "x"})
    with pytest.raises(ValueError, match="cost_center"):
        tagged(frag, SERVICE | {"cost_center": "nope"})
