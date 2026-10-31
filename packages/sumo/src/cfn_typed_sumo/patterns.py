"""Pattern helpers shown in the book (docs/). Sections feed the pages via pymdownx.snippets."""

# --8<-- [start:imports]
import re
from collections.abc import Collection, Mapping, Sequence
from dataclasses import asdict, dataclass, fields
from typing import Any, Literal, TypedDict

from cfn_typed_sumo.types import iam, lambda_, sqs

from cfn_typed import AnyResource, AnyStatement, Expr, Resources, Tag, allow, arn, assume_role_policy, get_att, policy_document, ref
from cfn_typed.policy import service
from cfn_typed.checks import Rule
from cfn_typed.query import prop, resources_of
from cfn_typed.rules import each, forbid, require

# --8<-- [end:imports]


# --8<-- [start:lambda_role]
def lambda_role(name_prefix: str, extra: Sequence[AnyStatement]) -> iam.Role:
    """Execution role for a Lambda: log permissions plus the `extra` statements."""
    log_arn = arn.log_group(f"/aws/lambda/{name_prefix}*", streams=True)
    return iam.role(
        AssumeRolePolicyDocument=assume_role_policy(service("lambda.amazonaws.com")),
        Policies=[iam.RolePolicyProperty(
            PolicyName=f"{name_prefix}-lambda",
            PolicyDocument=policy_document([
                allow(["logs:CreateLogStream", "logs:CreateLogGroup", "logs:PutLogEvents"], [log_arn]),
                *extra,
            ]),
        )],
    )
# --8<-- [end:lambda_role]


# --8<-- [start:sqs_event_source]
def sqs_event_source(function_logical: str, queue_arn: Expr[str], batch_size: int = 10) -> lambda_.EventSourceMapping:
    """Trigger the Lambda `function_logical` from an SQS queue."""
    return lambda_.event_source_mapping(
        BatchSize=batch_size,
        EventSourceArn=queue_arn,
        FunctionName=get_att(function_logical, "Arn"),
    )
# --8<-- [end:sqs_event_source]


# --8<-- [start:queue_with_dlq]
@dataclass(frozen=True)
class QueueWithDlq:
    """The handle `queue_with_dlq` returns: the logical IDs, how to refer to them, and the resources."""

    queue: str
    dlq: str
    resources: Resources

    @property
    def queue_arn(self) -> Expr[str]:
        return get_att(self.queue, "Arn")

    @property
    def queue_url(self) -> Expr[str]:
        return ref(self.queue)

    @property
    def dlq_url(self) -> Expr[str]:
        return ref(self.dlq)


def queue_with_dlq(
    name: str,
    *,
    visibility_timeout: int = 30,
    max_receive_count: int = 3,
    tags: list[Expr[Tag]] | None = None,
) -> QueueWithDlq:
    """A queue and its dead-letter queue, with logical IDs `{name}Queue` and `{name}DLQ`."""
    queue_id, dlq_id = f"{name}Queue", f"{name}DLQ"
    dlq: sqs.QueueProps = {}
    main: sqs.QueueProps = {
        "VisibilityTimeout": visibility_timeout,
        "RedrivePolicy": {"deadLetterTargetArn": get_att(dlq_id, "Arn"), "maxReceiveCount": max_receive_count},
    }
    if tags:
        dlq["Tags"] = main["Tags"] = tags
    return QueueWithDlq(queue_id, dlq_id, {dlq_id: sqs.queue(**dlq), queue_id: sqs.queue(**main)})


# --8<-- [end:queue_with_dlq]


# --8<-- [start:company_tags]
@dataclass(frozen=True, kw_only=True)
class CompanyTags:
    """The tags every taggable resource must end up with. No defaults, so a missing one is an error."""

    owner: str
    cost_center: str
    environment: Literal["dev", "test", "prod"]
    role: str

    def __post_init__(self) -> None:
        if not re.fullmatch(r"CC-\d{4}", self.cost_center):
            raise ValueError(f"cost_center must look like CC-1234, got {self.cost_center!r}")


REQUIRED = frozenset(f.name for f in fields(CompanyTags))


class SomeCompanyTags(TypedDict, total=False):
    """Any subset of the company tags: what a service sets for all its resources."""

    owner: str
    cost_center: str
    environment: Literal["dev", "test", "prod"]
    role: str


# The company decides which types it expects tags on; extend it as you adopt services.
TAGGABLE = frozenset({"AWS::SQS::Queue", "AWS::S3::Bucket", "AWS::DynamoDB::Table", "AWS::KMS::Key"})


def tagged(resources: Resources, service: SomeCompanyTags, *, taggable: Collection[str] = TAGGABLE) -> Resources:
    """Resolve the company tags for every taggable resource: its own tags over the `service` tags.

    Each resource must end up with all of `CompanyTags`, or this raises naming the resource and what is missing.
    Tags that are not company tags are left alone.
    """
    out: Resources = {}
    for logical_id, resource in resources.items():
        if resource["Type"] in taggable:
            props = dict(resource.get("Properties", {}))
            own = props.get("Tags", [])
            merged = {**service, **{t["Key"]: t["Value"] for t in own if t["Key"] in REQUIRED}}
            if missing := REQUIRED - merged.keys():
                raise ValueError(f"{logical_id} is missing company tags: {', '.join(sorted(missing))}")
            others = [t for t in own if t["Key"] not in REQUIRED]
            resolved = [{"Key": k, "Value": v} for k, v in asdict(CompanyTags(**merged)).items()]
            resource = AnyResource(**{**resource, "Properties": {**props, "Tags": [*others, *resolved]}})
        out[logical_id] = resource
    return out


def untagged(resources: Resources, *, taggable: Collection[str] = TAGGABLE) -> list[str]:
    """Logical IDs of taggable resources missing a company tag: a backstop for templates that skip `tagged`."""
    return [
        logical_id
        for logical_id, r in resources.items()
        if r["Type"] in taggable and REQUIRED - {t["Key"] for t in r.get("Properties", {}).get("Tags", [])}
    ]
# --8<-- [end:company_tags]


# --8<-- [start:company_rules]
def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else [] if value is None else [value]


@each("AWS::IAM::Role")
def no_admin_policies(logical_id: str, role: Mapping[str, Any]) -> list[str]:
    """No inline policy allows every action on every resource. Several problems per resource are fine."""
    return [
        f"Policies.{i} allows * on *"
        for i, policy in enumerate(prop(role, "Policies") or [])
        for st in as_list(policy["PolicyDocument"]["Statement"])
        if st["Effect"] == "Allow" and "*" in as_list(st.get("Action")) and "*" in as_list(st.get("Resource"))
    ]


@each("AWS::SQS::Queue")
def queue_names_say_what_they_are(logical_id: str, queue: Mapping[str, Any]) -> str | None:
    """Per-resource logic that `require` cannot express: the logical ID ends in Queue or DLQ."""
    return None if logical_id.endswith(("Queue", "DLQ")) else "name ends in neither Queue nor DLQ"


def queues_have_a_dead_letter_queue(template: Mapping[str, Any]) -> list[str]:
    """Logic across resources: every queue that is not itself a dead-letter queue redrives to one."""
    queues = resources_of(template, "AWS::SQS::Queue")
    targets = {
        t["Fn::GetAtt"][0]
        for q in queues.values()
        if isinstance(t := prop(q, "RedrivePolicy.deadLetterTargetArn"), dict) and "Fn::GetAtt" in t
    }
    return [f"{k}: no RedrivePolicy" for k, q in queues.items() if k not in targets and prop(q, "RedrivePolicy") is None]


COMPANY_RULES: list[Rule] = [
    require("AWS::S3::Bucket", "BucketEncryption"),
    *(require("AWS::S3::Bucket", f"PublicAccessBlockConfiguration.{s}", equals=True)
      for s in ("BlockPublicAcls", "BlockPublicPolicy", "IgnorePublicAcls", "RestrictPublicBuckets")),
    forbid("AWS::S3::Bucket", "AccessControl", one_of=["PublicRead", "PublicReadWrite"]),
    require("AWS::Logs::LogGroup", "RetentionInDays", at_least=30),
    no_admin_policies,
    queue_names_say_what_they_are,
    queues_have_a_dead_letter_queue,
]
# --8<-- [end:company_rules]
