"""Service-to-service wiring patterns shown in the book (docs/patterns/web-frontends.md, messaging.md, data-flows.md, containers.md).

Each one is the CDK / AWS Solutions Constructs idea of "A connected to B" written as a plain function: the resources,
and the permission that makes the connection actually work.
"""

# --8<-- [start:imports]
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from cfn_typed_sumo.types import apigateway, dynamodb, ecs, elasticloadbalancingv2 as elbv2, events
from cfn_typed_sumo.types import iam, kinesisfirehose, lambda_, logs, route53, s3, sns, sqs

from cfn_typed import AnyStatement, Expr, Resources, Tag, allow, arn, assume_role_policy, get_att, join, policy_document, ref, sub
from cfn_typed.policy import ANY, arn_equals, aws, service, string_equals
from cfn_typed_sumo.constructs import topic_to_queue
from cfn_typed_sumo.patterns import queue_with_dlq

# --8<-- [end:imports]


def _tags(props: Any, tags: list[Expr[Tag]] | None) -> None:
    if tags:
        props["Tags"] = tags


# =====================================================================================================================
# Web frontends
# =====================================================================================================================


# --8<-- [start:rest_api_deploy]
def _rest_api(name: str, *, description: str) -> tuple[str, apigateway.RestApi]:
    api = f"{name}Api"
    return api, apigateway.rest_api(Name=sub("${AWS::StackName}-" + name), Description=description)


def _deploy(name: str, api: str, methods: Sequence[str], stage: str) -> Resources:
    """A deployment and stage. The deployment depends on every method, or it can snapshot an empty API."""
    deployment = f"{name}Deployment"
    return {
        deployment: apigateway.deployment(RestApiId=ref(api), depends_on=list(methods)),
        f"{name}Stage": apigateway.stage(RestApiId=ref(api), DeploymentId=ref(deployment), StageName=stage),
    }
# --8<-- [end:rest_api_deploy]


# --8<-- [start:api_lambda]
def api_to_lambda(name: str, function_logical: str, *, stage: str = "prod") -> Resources:
    """A REST API that proxies every path and method to a Lambda function.

    Logical IDs: `{name}Api`, `{name}Proxy`, `{name}ProxyMethod`, `{name}RootMethod`, `{name}Deployment`,
    `{name}Stage` and `{name}InvokePermission`. The permission is the part people forget: without it
    API Gateway gets a 500 and nothing in the template says why.
    """
    api, rest = _rest_api(name, description=f"{name} proxy to {function_logical}")
    proxy = f"{name}Proxy"
    uri = sub(
        "arn:${AWS::Partition}:apigateway:${AWS::Region}:lambda:path/2015-03-31/functions/${Fn}/invocations",
        {"Fn": get_att(function_logical, "Arn")},
    )
    integration: apigateway.MethodIntegration = {"Type": "AWS_PROXY", "IntegrationHttpMethod": "POST", "Uri": uri}
    resources: Resources = {
        api: rest,
        proxy: apigateway.resource(RestApiId=ref(api), ParentId=get_att(api, "RootResourceId"), PathPart="{proxy+}"),
        f"{name}ProxyMethod": apigateway.method(
            RestApiId=ref(api), ResourceId=ref(proxy), HttpMethod="ANY", AuthorizationType="NONE", Integration=integration,
        ),
        # `{proxy+}` does not match the root path, so the root needs a method of its own
        f"{name}RootMethod": apigateway.method(
            RestApiId=ref(api), ResourceId=get_att(api, "RootResourceId"), HttpMethod="ANY", AuthorizationType="NONE", Integration=integration,
        ),
        f"{name}InvokePermission": lambda_.permission(
            Action="lambda:InvokeFunction",
            FunctionName=ref(function_logical),
            Principal="apigateway.amazonaws.com",
            SourceArn=sub("arn:${AWS::Partition}:execute-api:${AWS::Region}:${AWS::AccountId}:${A}/*/*/*", {"A": ref(api)}),
        ),
    }
    return resources | _deploy(name, api, [f"{name}ProxyMethod", f"{name}RootMethod"], stage)
# --8<-- [end:api_lambda]


# --8<-- [start:api_dynamodb]
def api_to_dynamodb(name: str, table_logical: str, *, key: str = "pk", stage: str = "prod") -> Resources:
    """`GET /items/{id}` straight from a table, with no Lambda in between.

    API Gateway calls DynamoDB `GetItem` itself, through a role that may read only this table. Logical IDs:
    `{name}Api`, `{name}Role`, `{name}Items`, `{name}Item`, `{name}GetMethod`, `{name}Deployment` and `{name}Stage`.
    """
    api, rest = _rest_api(name, description=f"{name} reads {table_logical}")
    items, item, method, role = f"{name}Items", f"{name}Item", f"{name}GetMethod", f"{name}Role"
    request = json.dumps({"TableName": "${T}", "Key": {key: {"S": "$input.params('id')"}}})
    resources: Resources = {
        api: rest,
        role: iam.role(
            AssumeRolePolicyDocument=assume_role_policy(service("apigateway.amazonaws.com")),
            Policies=[iam.RolePolicyProperty(
                PolicyName=f"{name}-read",
                PolicyDocument=policy_document([allow("dynamodb:GetItem", get_att(table_logical, "Arn"))]),
            )],
        ),
        items: apigateway.resource(RestApiId=ref(api), ParentId=get_att(api, "RootResourceId"), PathPart="items"),
        item: apigateway.resource(RestApiId=ref(api), ParentId=ref(items), PathPart="{id}"),
        method: apigateway.method(
            RestApiId=ref(api), ResourceId=ref(item), HttpMethod="GET", AuthorizationType="NONE",
            RequestParameters={"method.request.path.id": True},
            MethodResponses=[{"StatusCode": "200"}],
            Integration={
                "Type": "AWS",
                "IntegrationHttpMethod": "POST",
                "Uri": sub("arn:${AWS::Partition}:apigateway:${AWS::Region}:dynamodb:action/GetItem"),
                "Credentials": get_att(role, "Arn"),
                "RequestTemplates": {"application/json": sub(request, {"T": ref(table_logical)})},
                "IntegrationResponses": [{"StatusCode": "200"}],
            },
        ),
    }
    return resources | _deploy(name, api, [method], stage)
# --8<-- [end:api_dynamodb]


# --8<-- [start:alb_lambda]
def lambda_behind_alb(
    name: str,
    function_logical: str,
    *,
    listener: str,
    target_group_name: str,
    path_pattern: str,
    priority: int,
) -> Resources:
    """Send the requests that match `path_pattern` on an existing listener to a Lambda function.

    Logical IDs: `{name}TargetGroup`, `{name}InvokePermission` and `{name}Rule`. A Lambda target group has no
    VPC, port or health check. The target group must wait for the permission, or registering the function fails,
    so the permission cannot refer to the group (a cycle). It builds the group's ARN from the **fixed
    `target_group_name`** instead, which is why the name is required.
    """
    tg, permission = f"{name}TargetGroup", f"{name}InvokePermission"
    return {
        permission: lambda_.permission(
            Action="lambda:InvokeFunction",
            FunctionName=ref(function_logical),
            Principal="elasticloadbalancing.amazonaws.com",
            SourceArn=sub("arn:${AWS::Partition}:elasticloadbalancing:${AWS::Region}:${AWS::AccountId}:targetgroup/" + target_group_name + "/*"),
        ),
        tg: elbv2.target_group(
            Name=target_group_name,
            TargetType="lambda",
            Targets=[{"Id": get_att(function_logical, "Arn")}],
            depends_on=permission,
        ),
        f"{name}Rule": elbv2.listener_rule(
            ListenerArn=ref(listener),
            Priority=priority,
            Conditions=[{"Field": "path-pattern", "PathPatternConfig": {"Values": [path_pattern]}}],
            Actions=[{"Type": "forward", "TargetGroupArn": ref(tg)}],
        ),
    }
# --8<-- [end:alb_lambda]


# --8<-- [start:route53_alias]
CLOUDFRONT_HOSTED_ZONE = "Z2FDTNDATAQYW2"  # the same for every CloudFront distribution


def alias_to_load_balancer(logical_id: str, *, zone_id: Expr[str], record: str, load_balancer: str) -> Resources:
    """An A record in `zone_id` that points at a load balancer in this template."""
    return {logical_id: route53.record_set(
        HostedZoneId=zone_id,
        Name=record,
        Type="A",
        AliasTarget={
            "DNSName": get_att(load_balancer, "DNSName"),
            "HostedZoneId": get_att(load_balancer, "CanonicalHostedZoneID"),
            "EvaluateTargetHealth": True,
        },
    )}


def alias_to_distribution(logical_id: str, *, zone_id: Expr[str], record: str, distribution: str) -> Resources:
    """An A record in `zone_id` that points at a CloudFront distribution in this template."""
    return {logical_id: route53.record_set(
        HostedZoneId=zone_id,
        Name=record,
        Type="A",
        AliasTarget={
            "DNSName": get_att(distribution, "DomainName"),
            "HostedZoneId": CLOUDFRONT_HOSTED_ZONE,
            "EvaluateTargetHealth": False,
        },
    )}
# --8<-- [end:route53_alias]


# =====================================================================================================================
# Messaging and events
# =====================================================================================================================


# --8<-- [start:fan_out]
def fan_out(name: str, subscribers: Sequence[str], *, tags: list[Expr[Tag]] | None = None) -> Resources:
    """One topic, and for each subscriber its own queue with a dead-letter queue.

    Logical IDs: `{name}Topic`, and per subscriber `s`: `{s}Queue`, `{s}DLQ`, `{s}QueuePolicy` and
    `{s}Queue{name}TopicSubscription` (from the [CDK L2 `topic_to_queue`](cdk-l2.md)). A slow subscriber
    falls behind on its own queue instead of slowing the others.
    """
    topic = f"{name}Topic"
    topic_props: sns.TopicProps = {}
    _tags(topic_props, tags)
    resources: Resources = {topic: sns.topic(**topic_props)}
    for s in subscribers:
        q = queue_with_dlq(s, tags=tags)
        resources |= q.resources | topic_to_queue(q.queue, [topic], raw_message_delivery=True)
    return resources
# --8<-- [end:fan_out]


# --8<-- [start:event_rules]
def _rule(name: str, *, pattern: Mapping[str, Any] | None, schedule: str | None, target_id: str, target_arn: Expr[str]) -> events.Rule:
    if (pattern is None) == (schedule is None):
        raise ValueError("give exactly one of pattern and schedule")
    props: events.RuleProps = {"State": "ENABLED", "Targets": [{"Id": target_id, "Arn": target_arn}]}
    if pattern is not None:
        props["EventPattern"] = pattern
    if schedule is not None:
        props["ScheduleExpression"] = schedule
    return events.rule(**props)


def event_to_lambda(
    name: str, function_logical: str, *, pattern: Mapping[str, Any] | None = None, schedule: str | None = None,
) -> Resources:
    """An EventBridge rule that invokes a Lambda: `{name}Rule` and `{name}InvokePermission`.

    Give an event `pattern` or a `schedule` such as `"rate(5 minutes)"`. Lambda needs a permission naming this
    rule as the caller; the rule's target alone does not grant it.
    """
    rule = f"{name}Rule"
    return {
        rule: _rule(name, pattern=pattern, schedule=schedule, target_id=function_logical, target_arn=get_att(function_logical, "Arn")),
        f"{name}InvokePermission": lambda_.permission(
            Action="lambda:InvokeFunction",
            FunctionName=ref(function_logical),
            Principal="events.amazonaws.com",
            SourceArn=get_att(rule, "Arn"),
        ),
    }


def event_to_queue(
    name: str, queue: str, *, pattern: Mapping[str, Any] | None = None, schedule: str | None = None,
) -> Resources:
    """An EventBridge rule that sends to an SQS queue: `{name}Rule` and `{name}Policy`.

    The queue policy lets this rule, and only this rule, send. A queue encrypted with a customer-managed
    key would also need a key policy statement for `events.amazonaws.com`.
    """
    rule = f"{name}Rule"
    return {
        rule: _rule(name, pattern=pattern, schedule=schedule, target_id=queue, target_arn=get_att(queue, "Arn")),
        f"{name}Policy": sqs.queue_policy(
            Queues=[ref(queue)],
            PolicyDocument=policy_document([allow(
                "sqs:SendMessage", get_att(queue, "Arn"),
                principal=service("events.amazonaws.com"),
                condition=arn_equals("aws:SourceArn", get_att(rule, "Arn")),
            )]),
        ),
    }
# --8<-- [end:event_rules]


# =====================================================================================================================
# Data flows
# =====================================================================================================================


# --8<-- [start:stream_trigger]
@dataclass(frozen=True)
class StreamTrigger:
    """What `stream_trigger` returns: the mapping, and the statements the function's role needs to read the stream."""

    resources: Resources
    statements: list[AnyStatement]


def stream_trigger(
    name: str,
    function_logical: str,
    table_logical: str,
    *,
    batch_size: int = 100,
    starting_position: Literal["LATEST", "TRIM_HORIZON"] = "LATEST",
    max_retries: int = 3,
) -> StreamTrigger:
    """Invoke a Lambda for the changes of a DynamoDB table: `{name}StreamMapping`.

    The table needs a `StreamSpecification` (see `with_stream`). The function's role needs `statements`, and a
    stream mapping that fails keeps retrying the same batch until the record expires, so retries are bounded
    and a bad batch is split in half to isolate the record that fails.
    """
    mapping = lambda_.event_source_mapping(
        FunctionName=get_att(function_logical, "Arn"),
        EventSourceArn=get_att(table_logical, "StreamArn"),
        StartingPosition=starting_position,
        BatchSize=batch_size,
        BisectBatchOnFunctionError=True,
        MaximumRetryAttempts=max_retries,
    )
    stream = get_att(table_logical, "StreamArn")
    return StreamTrigger(
        {f"{name}StreamMapping": mapping},
        [
            allow(["dynamodb:DescribeStream", "dynamodb:GetRecords", "dynamodb:GetShardIterator"], stream),
            allow("dynamodb:ListStreams", "*"),
        ],
    )


def with_stream(table: dynamodb.Table, view: Literal["KEYS_ONLY", "NEW_IMAGE", "OLD_IMAGE", "NEW_AND_OLD_IMAGES"] = "NEW_AND_OLD_IMAGES") -> dynamodb.Table:
    """The same table with a stream. The table is not modified."""
    return dynamodb.Table(**{**table, "Properties": {**table["Properties"], "StreamSpecification": {"StreamViewType": view}}})
# --8<-- [end:stream_trigger]


# --8<-- [start:bucket_to_lambda]
def bucket_to_lambda(
    name: str,
    function_logical: str,
    *,
    bucket_name: str,
    events: Sequence[str] = ("s3:ObjectCreated:*",),
    prefix: str | None = None,
    suffix: str | None = None,
) -> Resources:
    """A private bucket that invokes a Lambda when objects arrive: `{name}Bucket` and `{name}InvokePermission`.

    The bucket **must have a fixed name**. The permission has to exist before the bucket can be created (S3 tests
    the notification when it is set), but a permission that names the bucket with `GetAtt` would make the bucket
    wait for itself. So the permission builds the bucket's ARN from the name, and the bucket depends on it.
    """
    bucket, permission = f"{name}Bucket", f"{name}InvokePermission"
    rules: list[Expr[s3.BucketFilterRule]] = [{"Name": k, "Value": v} for k, v in (("prefix", prefix), ("suffix", suffix)) if v]
    notifications: list[Expr[s3.BucketLambdaConfiguration]] = []
    for event in events:
        n: s3.BucketLambdaConfiguration = {"Event": event, "Function": get_att(function_logical, "Arn")}
        if rules:
            n["Filter"] = {"S3Key": {"Rules": rules}}
        notifications.append(n)
    return {
        permission: lambda_.permission(
            Action="lambda:InvokeFunction",
            FunctionName=ref(function_logical),
            Principal="s3.amazonaws.com",
            SourceAccount=ref("AWS::AccountId"),
            SourceArn=arn.bucket(bucket_name),
        ),
        bucket: s3.bucket(
            BucketName=bucket_name,
            PublicAccessBlockConfiguration={
                "BlockPublicAcls": True, "BlockPublicPolicy": True, "IgnorePublicAcls": True, "RestrictPublicBuckets": True,
            },
            NotificationConfiguration={"LambdaConfigurations": notifications},
            depends_on=permission,
        ),
    }
# --8<-- [end:bucket_to_lambda]


# --8<-- [start:firehose_to_s3]
def firehose_to_s3(
    name: str,
    *,
    bucket_arn: Expr[str],
    prefix: str = "firehose/",
    buffer_seconds: int = 300,
    buffer_mb: int = 64,
    retention_days: int = 30,
) -> Resources:
    """A Firehose delivery stream that writes GZIP files to a bucket, with its role and logs.

    Logical IDs: `{name}Logs`, `{name}LogStream`, `{name}Role` and `{name}Stream`. The role may write only
    to `bucket_arn` and to its own log group. Firehose does not create the log stream, so the pattern does.
    """
    logs_id, stream_id, role = f"{name}Logs", f"{name}LogStream", f"{name}Role"
    return {
        logs_id: logs.log_group(RetentionInDays=retention_days),
        stream_id: logs.log_stream(LogGroupName=ref(logs_id), LogStreamName="DestinationDelivery"),
        role: iam.role(
            AssumeRolePolicyDocument=assume_role_policy(
                service("firehose.amazonaws.com"),
                condition=string_equals("sts:ExternalId", ref("AWS::AccountId")),
            ),
            Policies=[iam.RolePolicyProperty(
                PolicyName=f"{name}-deliver",
                PolicyDocument=policy_document([
                    allow(["s3:GetBucketLocation", "s3:ListBucket", "s3:ListBucketMultipartUploads"], bucket_arn),
                    allow(["s3:AbortMultipartUpload", "s3:GetObject", "s3:PutObject"], join("", [bucket_arn, "/*"])),
                    allow("logs:PutLogEvents", get_att(logs_id, "Arn")),
                ]),
            )],
        ),
        f"{name}Stream": kinesisfirehose.delivery_stream(
            DeliveryStreamType="DirectPut",
            ExtendedS3DestinationConfiguration={
                "BucketARN": bucket_arn,
                "RoleARN": get_att(role, "Arn"),
                "Prefix": prefix,
                "ErrorOutputPrefix": f"{prefix}errors/",
                "CompressionFormat": "GZIP",
                "BufferingHints": {"IntervalInSeconds": buffer_seconds, "SizeInMBs": buffer_mb},
                "CloudWatchLoggingOptions": {"Enabled": True, "LogGroupName": ref(logs_id), "LogStreamName": "DestinationDelivery"},
            },
            depends_on=stream_id,
        ),
    }
# --8<-- [end:firehose_to_s3]


# =====================================================================================================================
# Containers
# =====================================================================================================================


# --8<-- [start:fargate_task]
@dataclass(frozen=True)
class FargateTask:
    """What `fargate_task` returns: the resources, and what a Lambda needs to start tasks of it on demand."""

    name: str
    resources: Resources
    subnets: Expr[list[Expr[str]]]
    security_groups: list[Expr[str]]

    @property
    def cluster_arn(self) -> Expr[str]:
        return get_att(f"{self.name}Cluster", "Arn")

    @property
    def task_definition_arn(self) -> Expr[str]:
        return ref(f"{self.name}Task")

    @property
    def run_task_statements(self) -> list[AnyStatement]:
        """For the invoking Lambda's role: `RunTask` on this task definition, and `PassRole` for the task's two roles."""
        return [
            allow("ecs:RunTask", self.task_definition_arn, condition=arn_equals("ecs:cluster", self.cluster_arn)),
            allow("iam:PassRole", [get_att(f"{self.name}ExecutionRole", "Arn"), get_att(f"{self.name}TaskRole", "Arn")]),
        ]

    @property
    def environment(self) -> dict[str, Expr[str]]:
        """Variables for the invoking Lambda, so the template, not a string in the code, says where tasks run."""
        return {
            "CLUSTER_ARN": self.cluster_arn,
            "TASK_DEFINITION_ARN": self.task_definition_arn,
            "SUBNETS": join(",", self.subnets),
            "SECURITY_GROUPS": self.security_groups[0],
        }


def fargate_task(
    name: str,
    *,
    image: Expr[str],
    subnets: Expr[list[Expr[str]]],
    security_groups: list[Expr[str]],
    cpu: Literal["256", "512", "1024", "2048", "4096"] = "256",
    memory: Literal["512", "1024", "2048", "4096", "8192"] = "512",
    desired_count: int | None = 1,
    port: int | None = None,
    environment: Mapping[str, Expr[str]] | None = None,
    task_statements: Sequence[AnyStatement] = (),
    retention_days: int = 30,
    tags: list[Expr[Tag]] | None = None,
) -> FargateTask:
    """A cluster, a task definition and (with `desired_count`) a service running one container, with no load balancer.

    For a web service behind a load balancer see `fargate_service` in [CDK L2 constructs](cdk-l2.md). This one is
    for workers, and for tasks that a Lambda starts.

    Logical IDs: `{name}Cluster`, `{name}Logs`, `{name}ExecutionRole`, `{name}TaskRole`, `{name}Task` and
    `{name}Service`. The **execution role** is what ECS uses to pull the image and write logs, and the **task
    role** is what your code runs as, with `task_statements`. Mixing the two up is the usual mistake.
    Pass `desired_count=None` for a task that is only started on demand (`run_task_statements`).
    """
    logs_id, execution, task_role, task, svc, cluster = (
        f"{name}Logs", f"{name}ExecutionRole", f"{name}TaskRole", f"{name}Task", f"{name}Service", f"{name}Cluster",
    )
    container: ecs.TaskDefinitionContainerDefinition = {
        "Name": name,
        "Image": image,
        "Essential": True,
        "LogConfiguration": {"LogDriver": "awslogs", "Options": {
            "awslogs-group": ref(logs_id), "awslogs-region": ref("AWS::Region"), "awslogs-stream-prefix": name,
        }},
    }
    if port:
        container["PortMappings"] = [{"ContainerPort": port, "Protocol": "tcp"}]
    if environment:
        container["Environment"] = [{"Name": k, "Value": v} for k, v in environment.items()]
    task_props: ecs.TaskDefinitionProps = {
        "Family": name,
        "Cpu": cpu,
        "Memory": memory,
        "NetworkMode": "awsvpc",
        "RequiresCompatibilities": ["FARGATE"],
        "ExecutionRoleArn": get_att(execution, "Arn"),
        "TaskRoleArn": get_att(task_role, "Arn"),
        "ContainerDefinitions": [container],
    }
    role_props: iam.RoleProps = {"AssumeRolePolicyDocument": assume_role_policy(service("ecs-tasks.amazonaws.com"))}
    if task_statements:
        role_props["Policies"] = [iam.RolePolicyProperty(PolicyName=f"{name}-task", PolicyDocument=policy_document(task_statements))]
    cluster_props: ecs.ClusterProps = {"ClusterSettings": [{"Name": "containerInsights", "Value": "enabled"}]}
    _tags(task_props, tags)
    _tags(cluster_props, tags)
    resources: Resources = {
        cluster: ecs.cluster(**cluster_props),
        logs_id: logs.log_group(RetentionInDays=retention_days),
        execution: iam.role(
            AssumeRolePolicyDocument=assume_role_policy(service("ecs-tasks.amazonaws.com")),
            ManagedPolicyArns=[sub("arn:${AWS::Partition}:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy")],
        ),
        task_role: iam.role(**role_props),
        task: ecs.task_definition(**task_props),
    }
    if desired_count is not None:
        service_props: ecs.ServiceProps = {
            "Cluster": ref(cluster),
            "TaskDefinition": ref(task),
            "DesiredCount": desired_count,
            "LaunchType": "FARGATE",
            "NetworkConfiguration": {"AwsvpcConfiguration": {
                "Subnets": subnets, "SecurityGroups": security_groups, "AssignPublicIp": "DISABLED",
            }},
            "DeploymentConfiguration": {"DeploymentCircuitBreaker": {"Enable": True, "Rollback": True}},
        }
        _tags(service_props, tags)
        resources[svc] = ecs.service(**service_props)
    return FargateTask(name, resources, subnets, security_groups)
# --8<-- [end:fargate_task]
