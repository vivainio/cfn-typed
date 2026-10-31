from cfn_typed_sumo.patterns import COMPANY_RULES, CompanyTags, SomeCompanyTags, lambda_role, queue_with_dlq, sqs_event_source, tagged, untagged  # noqa: E402

import pytest  # noqa: E402

from cfn_typed import Resources, get_att, ref, tags  # noqa: E402
from cfn_typed.checks import find_all_problems  # noqa: E402
from cfn_typed.query import prop, resources_of  # noqa: E402
from cfn_typed.rules import each, forbid, require  # noqa: E402
from cfn_typed.testing import assert_template_ok  # noqa: E402


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


BAD = {
    "Resources": {
        "Bucket": {"Type": "AWS::S3::Bucket", "Properties": {"PublicAccessBlockConfiguration": {"BlockPublicAcls": True}}},
        "Lonely": {"Type": "AWS::SQS::Queue"},
        "Logs": {"Type": "AWS::Logs::LogGroup", "Properties": {"RetentionInDays": 7}},
        "Role": {"Type": "AWS::IAM::Role", "Properties": {"Policies": [
            {"PolicyName": "p", "PolicyDocument": {"Statement": {"Effect": "Allow", "Action": "*", "Resource": "*"}}},
        ]}},
    },
}


def test_company_rules_are_one_more_layer_on_the_checks() -> None:
    found = find_all_problems(BAD, rules=COMPANY_RULES)
    assert found["AWS::S3::Bucket.BucketEncryption required"] == ["Bucket: BucketEncryption is not set"]
    assert found["AWS::S3::Bucket.PublicAccessBlockConfiguration.BlockPublicPolicy equals=True required"] == [
        "Bucket: PublicAccessBlockConfiguration.BlockPublicPolicy is not set"
    ]
    assert "AWS::S3::Bucket.PublicAccessBlockConfiguration.BlockPublicAcls equals=True required" not in found
    assert found["queues_have_a_dead_letter_queue"] == ["Lonely: no RedrivePolicy"]
    assert found["no_admin_policies"] == ["Role: Policies.0 allows * on *"]
    assert found["AWS::Logs::LogGroup.RetentionInDays at_least=30 required"] == [
        "Logs: RetentionInDays is 7, expected at least 30"
    ]
    assert found["queue_names_say_what_they_are"] == ["Lonely: name ends in neither Queue nor DLQ"]
    with pytest.raises(AssertionError, match=r"\[no_admin_policies\] Role"):
        assert_template_ok(BAD, rules=COMPANY_RULES)


def test_company_rules_pass_the_example_patterns() -> None:
    template = {"Resources": queue_with_dlq("Order").resources}
    assert_template_ok(template, rules=COMPANY_RULES)


def test_query_helpers() -> None:
    assert list(resources_of(BAD, "AWS::SQS::Queue", "AWS::Logs::LogGroup")) == ["Lonely", "Logs"]
    role = BAD["Resources"]["Role"]
    assert prop(role, "Policies.0.PolicyName") == "p"
    assert prop(role, "Policies.1.PolicyName") is None
    assert prop(role, "Nope.Deeper") is None
    assert prop({"Properties": {"X": {"Ref": "AWS::NoValue"}}}, "X") is None


def test_require_and_forbid_conditions() -> None:
    t = {"Resources": {
        "A": {"Type": "AWS::S3::Bucket", "Properties": {"AccessControl": "PublicRead", "N": 5, "S": "ab", "U": {"Ref": "P"}}},
        "B": {"Type": "AWS::S3::Bucket", "Properties": {"AccessControl": "Private"}},
        "C": {"Type": "AWS::SQS::Queue"},
    }}
    assert forbid("AWS::S3::Bucket", "AccessControl", one_of=["PublicRead"])(t) == ["A: AccessControl is 'PublicRead', which is not allowed"]
    assert forbid(["AWS::S3::Bucket", "AWS::SQS::Queue"], "AccessControl")(t) == [
        "A: AccessControl is 'PublicRead', which is not allowed", "B: AccessControl is 'Private', which is not allowed"]
    assert require("AWS::S3::Bucket", "N", at_least=1, at_most=3)(t)[0] == "A: N is 5, expected at most 3"
    assert require("AWS::S3::Bucket", "S", matches=r"\d+", unless=lambda i, r: i == "B")(t) == [r"A: S is 'ab', expected to match \d+"]
    assert require("AWS::S3::Bucket", "U", equals="x", unless=lambda i, r: i == "B")(t) == []  # a Ref counts as set, and is not compared
    assert require("AWS::S3::Bucket", "N", at_least=1)(t) == ["B: N is not set"]
    assert require(("AWS::S3::Bucket", "AWS::SQS::Queue"), "AccessControl", equals="Private")(t)[-1] == "C: AccessControl is not set"
