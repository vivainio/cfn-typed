"""AWS CDK L2 constructs rebuilt as patterns, shown in the book (docs/patterns/cdk-l2.md)."""

# --8<-- [start:imports]
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from cfn_types import applicationautoscaling as appscaling
from cfn_types import cloudwatch, ec2, ecs, events, iam, lambda_, logs, sns, sqs

from cfn_typed import (
    AnyStatement, Expr, Resources, Tag, allow, assume_role_policy, cidr, get_att, get_azs, join, ref, select, sub,
)
from cfn_typed.policy import arn_equals, service
from loadbalancer import allow_from, listener, load_balancer, target_group

# --8<-- [end:imports]


# --8<-- [start:function]
@dataclass(frozen=True)
class Function:
    """The handle `function` returns: the logical IDs, how to refer to them, and the resources."""

    function: str
    role: str
    log_group: str
    resources: Resources

    @property
    def arn(self) -> Expr[str]:
        return get_att(self.function, "Arn")

    @property
    def role_arn(self) -> Expr[str]:
        return get_att(self.role, "Arn")


def function(
    name: str,
    *,
    code: lambda_.FunctionCode,
    handler: str,
    runtime: str,
    memory: int = 128,
    timeout: int = 3,
    environment: Mapping[str, Expr[str]] | None = None,
    statements: Sequence[AnyStatement] = (),
    log_retention_days: int = 30,
    tags: list[Expr[Tag]] | None = None,
) -> Function:
    """`lambda.Function`: the function, its execution role and its log group, `{name}`, `{name}Role` and `{name}Logs`.

    The role can write logs and carries `statements`. The log group is created here, with a retention, instead of
    by Lambda on the first call, where it would never expire and would outlive the stack.
    """
    role, logs_id = f"{name}Role", f"{name}Logs"
    role_props: iam.RoleProps = {
        "AssumeRolePolicyDocument": assume_role_policy(service("lambda.amazonaws.com")),
        "ManagedPolicyArns": [sub("arn:${AWS::Partition}:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole")],
    }
    logs_props: logs.LogGroupProps = {"RetentionInDays": log_retention_days}
    props: lambda_.FunctionProps = {
        "Code": code, "Handler": handler, "Runtime": runtime, "MemorySize": memory, "Timeout": timeout,
        "Role": get_att(role, "Arn"),
        "LoggingConfig": {"LogGroup": ref(logs_id)},
    }
    if statements:
        role_props["Policies"] = [iam.RolePolicy(
            PolicyName=f"{name}-inline", PolicyDocument={"Version": "2012-10-17", "Statement": list(statements)},
        )]
    if environment:
        props["Environment"] = {"Variables": environment}
    if tags:
        role_props["Tags"] = logs_props["Tags"] = props["Tags"] = tags
    return Function(name, role, logs_id, {
        role: iam.role(**role_props),
        logs_id: logs.log_group(**logs_props),
        name: lambda_.function(**props),
    })
# --8<-- [end:function]


# --8<-- [start:invoke_permission]
def invoke_permission(function_logical: str, principal: str, source_arn: Expr[str]) -> lambda_.Permission:
    """`grantInvoke` for a service: let `principal` (`"events.amazonaws.com"`) invoke the function, from `source_arn` only."""
    return lambda_.permission(
        Action="lambda:InvokeFunction",
        FunctionName=ref(function_logical),
        Principal=principal,
        SourceArn=source_arn,
    )
# --8<-- [end:invoke_permission]


# --8<-- [start:schedule]
def schedule(name: str, expression: str, function_logical: str, *, enabled: bool = True) -> Resources:
    """`events.Rule` with a `LambdaFunction` target: the rule and the permission it needs, `{name}Rule`, `{name}Permission`.

    `expression` is `"rate(5 minutes)"` or `"cron(0 8 * * ? *)"`. Without the permission the rule would match and
    the function would never run, with no error anywhere, which is why the two always travel together.
    """
    rule = f"{name}Rule"
    return {
        rule: events.rule(
            ScheduleExpression=expression,
            State="ENABLED" if enabled else "DISABLED",
            Targets=[{"Id": "Target0", "Arn": get_att(function_logical, "Arn")}],
        ),
        f"{name}Permission": invoke_permission(function_logical, "events.amazonaws.com", get_att(rule, "Arn")),
    }
# --8<-- [end:schedule]


# --8<-- [start:topic_to_queue]
def topic_to_queue(
    queue: str,
    topics: Sequence[str],
    *,
    raw_message_delivery: bool = False,
    filter_policy: Mapping[str, Sequence[str]] | None = None,
) -> Resources:
    """`SqsSubscription`: one subscription per topic, and the one queue policy that lets them all send.

    Logical IDs are `{queue}{topic}Subscription` and `{queue}Policy`. A queue has a single policy, so all of its
    topics go through one call. The CDK gets there by editing a policy it already holds; a pattern has no such
    state, and having the topics as the argument is how it avoids a policy per call overwriting the one before.
    """
    resources: Resources = {
        f"{queue}Policy": sqs.queue_policy(
            Queues=[ref(queue)],
            PolicyDocument={"Version": "2012-10-17", "Statement": [
                allow("sqs:SendMessage", get_att(queue, "Arn"), principal=service("sns.amazonaws.com"),
                      condition=arn_equals("aws:SourceArn", [ref(t) for t in topics])),
            ]},
        ),
    }
    for topic in topics:
        props: sns.SubscriptionProps = {
            "TopicArn": ref(topic), "Protocol": "sqs", "Endpoint": get_att(queue, "Arn"),
            "RawMessageDelivery": raw_message_delivery,
        }
        if filter_policy:
            props["FilterPolicy"] = filter_policy
        resources[f"{queue}{topic}Subscription"] = sns.subscription(**props)
    return resources
# --8<-- [end:topic_to_queue]


# --8<-- [start:vpc]
@dataclass(frozen=True)
class Vpc:
    """The handle `vpc` returns: the VPC and its subnets, one of each kind per availability zone."""

    vpc: str
    public: list[str]
    private: list[str]
    resources: Resources

    @property
    def vpc_id(self) -> Expr[str]:
        return ref(self.vpc)

    @property
    def public_subnet_ids(self) -> list[Expr[str]]:
        return [ref(s) for s in self.public]

    @property
    def private_subnet_ids(self) -> list[Expr[str]]:
        return [ref(s) for s in self.private]


def vpc(name: str, *, cidr_block: str = "10.0.0.0/16", zones: int = 2, nat_gateways: bool = True) -> Vpc:
    """`ec2.Vpc`: public and private subnets in `zones` availability zones, an internet gateway, and a NAT gateway per zone.

    Logical IDs are `{name}`, `{name}Gateway`, `{name}PublicRoutes`, and per zone `{name}Public1`, `{name}Private1`,
    `{name}Nat1` and so on, counting from 1. Subnets are /24 blocks carved with `Fn::Cidr`. `nat_gateways=False`
    leaves the private subnets without a route out, and is what you want for a stack that only talks to endpoints.
    """
    gateway, public_routes = f"{name}Gateway", f"{name}PublicRoutes"
    blocks = cidr(cidr_block, 2 * zones, 8)  # the first `zones` blocks are public, the rest private
    public: list[str] = []
    private: list[str] = []
    resources: Resources = {
        name: ec2.vpc(CidrBlock=cidr_block, EnableDnsSupport=True, EnableDnsHostnames=True),
        gateway: ec2.internet_gateway(),
        f"{gateway}Attachment": ec2.vpc_gateway_attachment(VpcId=ref(name), InternetGatewayId=ref(gateway)),
        public_routes: ec2.route_table(VpcId=ref(name)),
        f"{public_routes}Default": ec2.route(
            RouteTableId=ref(public_routes), DestinationCidrBlock="0.0.0.0/0", GatewayId=ref(gateway),
            depends_on=f"{gateway}Attachment",
        ),
    }
    for i in range(zones):
        n = i + 1
        az = select(i, get_azs())
        pub, priv, nat = f"{name}Public{n}", f"{name}Private{n}", f"{name}Nat{n}"
        public.append(pub)
        private.append(priv)
        resources |= {
            pub: ec2.subnet(VpcId=ref(name), AvailabilityZone=az, CidrBlock=select(i, blocks), MapPublicIpOnLaunch=True),
            f"{pub}Routes": ec2.subnet_route_table_association(SubnetId=ref(pub), RouteTableId=ref(public_routes)),
            priv: ec2.subnet(VpcId=ref(name), AvailabilityZone=az, CidrBlock=select(zones + i, blocks)),
            f"{priv}RouteTable": ec2.route_table(VpcId=ref(name)),
            f"{priv}Routes": ec2.subnet_route_table_association(SubnetId=ref(priv), RouteTableId=ref(f"{priv}RouteTable")),
        }
        if nat_gateways:
            resources |= {
                f"{nat}Ip": ec2.eip(Domain="vpc", depends_on=f"{gateway}Attachment"),
                nat: ec2.nat_gateway(SubnetId=ref(pub), AllocationId=get_att(f"{nat}Ip", "AllocationId")),
                f"{priv}Default": ec2.route(
                    RouteTableId=ref(f"{priv}RouteTable"), DestinationCidrBlock="0.0.0.0/0", NatGatewayId=ref(nat),
                ),
            }
    return Vpc(name, public, private, resources)
# --8<-- [end:vpc]


# --8<-- [start:fargate_service]
@dataclass(frozen=True)
class FargateService:
    """The handle `fargate_service` returns: the logical IDs callers need, how to refer to them, and the resources."""

    name: str
    resources: Resources

    @property
    def task_role_arn(self) -> Expr[str]:
        return get_att(f"{self.name}TaskRole", "Arn")

    @property
    def dns_name(self) -> Expr[str]:
        return get_att(f"{self.name}LoadBalancer", "DNSName")


def fargate_service(
    name: str,
    *,
    vpc_id: Expr[str],
    public_subnets: Expr[list[Expr[str]]],
    private_subnets: Expr[list[Expr[str]]],
    image: str,
    port: int = 80,
    cpu: str = "256",
    memory: str = "512",
    desired_count: int = 2,
    environment: Mapping[str, Expr[str]] | None = None,
    statements: Sequence[AnyStatement] = (),
    health_check_path: str = "/",
    certificate_arn: Expr[str] | None = None,
    log_retention_days: int = 30,
    tags: list[Expr[Tag]] | None = None,
) -> FargateService:
    """`ApplicationLoadBalancedFargateService`: a cluster, a task, a service and an internet-facing load balancer.

    Logical IDs are `{name}Cluster`, `{name}Logs`, `{name}TaskRole`, `{name}ExecutionRole`, `{name}Task`,
    `{name}Service`, and `{name}LoadBalancer` with its `{name}LoadBalancerGroup`, `{name}TargetGroup` and
    `{name}Listener`. The tasks run in the private subnets and accept traffic from the load balancer only
    (`{name}ServiceGroup`, `{name}FromLoadBalancer`). `statements` go to the task role, which is what the
    application's own code runs as.
    """
    lb, lb_group, group = f"{name}LoadBalancer", f"{name}LoadBalancerGroup", f"{name}ServiceGroup"
    tg, lis, logs_id = f"{name}TargetGroup", f"{name}Listener", f"{name}Logs"
    task_role, exec_role = f"{name}TaskRole", f"{name}ExecutionRole"
    trust = assume_role_policy(service("ecs-tasks.amazonaws.com"))
    role_props: iam.RoleProps = {"AssumeRolePolicyDocument": trust}
    if statements:
        role_props["Policies"] = [iam.RolePolicy(
            PolicyName=f"{name}-task", PolicyDocument={"Version": "2012-10-17", "Statement": list(statements)},
        )]
    container: ecs.TaskDefinitionContainerDefinition = {
        "Name": name, "Image": image, "Essential": True,
        "PortMappings": [{"ContainerPort": port}],
        "LogConfiguration": {"LogDriver": "awslogs", "Options": {
            "awslogs-group": ref(logs_id), "awslogs-region": ref("AWS::Region"), "awslogs-stream-prefix": name,
        }},
    }
    if environment:
        container["Environment"] = [{"Name": k, "Value": v} for k, v in environment.items()]
    resources: Resources = {
        f"{name}Cluster": ecs.cluster(),
        logs_id: logs.log_group(RetentionInDays=log_retention_days),
        task_role: iam.role(**role_props),
        exec_role: iam.role(
            AssumeRolePolicyDocument=trust,
            ManagedPolicyArns=[sub("arn:${AWS::Partition}:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy")],
        ),
        f"{name}Task": ecs.task_definition(
            Family=name, Cpu=cpu, Memory=memory, NetworkMode="awsvpc", RequiresCompatibilities=["FARGATE"],
            TaskRoleArn=get_att(task_role, "Arn"), ExecutionRoleArn=get_att(exec_role, "Arn"),
            ContainerDefinitions=[container],
        ),
        lb_group: ec2.security_group(
            GroupDescription=f"{name} load balancer", VpcId=vpc_id,
            SecurityGroupIngress=[{"IpProtocol": "tcp", "FromPort": p, "ToPort": p, "CidrIp": "0.0.0.0/0"}
                                  for p in ([443] if certificate_arn else [80])],
        ),
        group: ec2.security_group(GroupDescription=f"{name} service", VpcId=vpc_id),
        f"{name}FromLoadBalancer": allow_from(group, lb_group, port),
        lb: load_balancer(subnets=public_subnets, security_groups=[ref(lb_group)], tags=tags),
        tg: target_group(vpc_id=vpc_id, port=port, health_check_path=health_check_path, target_type="ip", tags=tags),
        lis: listener(
            load_balancer=lb, target_group=tg, port=443 if certificate_arn else 80, certificate_arn=certificate_arn,
        ),
        f"{name}Service": ecs.service(
            Cluster=ref(f"{name}Cluster"), TaskDefinition=ref(f"{name}Task"), LaunchType="FARGATE",
            DesiredCount=desired_count,
            NetworkConfiguration={"AwsvpcConfiguration": {
                "Subnets": private_subnets, "SecurityGroups": [ref(group)], "AssignPublicIp": "DISABLED",
            }},
            LoadBalancers=[{"TargetGroupArn": ref(tg), "ContainerName": name, "ContainerPort": port}],
            # the target group is not attached to the load balancer until the listener exists
            depends_on=lis,
        ),
    }
    return FargateService(name, resources)
# --8<-- [end:fargate_service]


# --8<-- [start:alarm]
def alarm(
    namespace: str,
    metric: str,
    *,
    dimensions: Mapping[str, Expr[str]],
    threshold: float,
    comparison: str = "GreaterThanOrEqualToThreshold",
    statistic: str = "Average",
    period: int = 300,
    evaluation_periods: int = 1,
    datapoints_to_alarm: int | None = None,
    treat_missing_data: str = "notBreaching",
    actions: Sequence[Expr[str]] = (),
    ok_actions: Sequence[Expr[str]] = (),
    description: str = "",
) -> cloudwatch.Alarm:
    """`metric.createAlarm`: one alarm on one metric. `actions` run when it fires, `ok_actions` when it recovers.

    Missing data does not breach by default, because a metric that is only published when something happens
    (an error count) would otherwise sit in `INSUFFICIENT_DATA` and never recover.
    """
    props: cloudwatch.AlarmProps = {
        "Namespace": namespace, "MetricName": metric, "Statistic": statistic, "Period": period,
        "Dimensions": [{"Name": k, "Value": v} for k, v in dimensions.items()],
        "Threshold": threshold, "ComparisonOperator": comparison,
        "EvaluationPeriods": evaluation_periods, "TreatMissingData": treat_missing_data,
    }
    if datapoints_to_alarm is not None:
        props["DatapointsToAlarm"] = datapoints_to_alarm
    if description:
        props["AlarmDescription"] = description
    if actions:
        props["AlarmActions"] = list(actions)
    if ok_actions:
        props["OKActions"] = list(ok_actions)
    return cloudwatch.alarm(**props)
# --8<-- [end:alarm]


# --8<-- [start:alarm_helpers]
def queue_backlog_alarm(queue: str, *, threshold: int, actions: Sequence[Expr[str]] = (), minutes: int = 5) -> cloudwatch.Alarm:
    """`queue.metricApproximateNumberOfMessagesVisible().createAlarm`: too many messages waiting for `minutes`."""
    return alarm(
        "AWS/SQS", "ApproximateNumberOfMessagesVisible", dimensions={"QueueName": get_att(queue, "QueueName")},
        threshold=threshold, statistic="Maximum", period=60, evaluation_periods=minutes, actions=actions, ok_actions=actions,
        description=f"{queue} has had more than {threshold} messages waiting for {minutes} minutes",
    )


def lambda_errors_alarm(function_logical: str, *, threshold: int = 1, actions: Sequence[Expr[str]] = ()) -> cloudwatch.Alarm:
    """`fn.metricErrors().createAlarm`: the function failed at least `threshold` times in a minute."""
    return alarm(
        "AWS/Lambda", "Errors", dimensions={"FunctionName": ref(function_logical)}, threshold=threshold,
        statistic="Sum", period=60, actions=actions, ok_actions=actions, description=f"{function_logical} is failing",
    )


def alarm_topic(name: str, emails: Sequence[str]) -> Resources:
    """A topic for alarms to notify, with an email subscription each: `{name}Topic` and `{name}Email{n}`."""
    topic = f"{name}Topic"
    return {topic: sns.topic(), **{
        f"{name}Email{n}": sns.subscription(TopicArn=ref(topic), Protocol="email", Endpoint=email)
        for n, email in enumerate(emails, 1)
    }}
# --8<-- [end:alarm_helpers]


# --8<-- [start:composite_alarm]
def composite_alarm(
    name: str,
    alarms: Sequence[str],
    *,
    when: Literal["any", "all"] = "all",
    actions: Sequence[Expr[str]] = (),
    description: str = "",
) -> cloudwatch.CompositeAlarm:
    """`CompositeAlarm.fromAlarms`: fires when `any` or `all` of the alarms with these logical IDs are in `ALARM`.

    A backlog alone is noise, and so are errors alone. A backlog *and* errors is something to wake someone for.
    The rule is built from the alarms' ARNs, so the template depends on all of them.
    """
    states: list[Expr[str]] = [sub(f"ALARM(${{{a}.Arn}})") for a in alarms]
    props: cloudwatch.CompositeAlarmProps = {"AlarmRule": join(" AND " if when == "all" else " OR ", states)}
    if description:
        props["AlarmDescription"] = description
    if actions:
        props["AlarmActions"] = props["OKActions"] = list(actions)
    return cloudwatch.composite_alarm(**props)
# --8<-- [end:composite_alarm]


# --8<-- [start:service_scaling]
def _scalable_target(cluster: str, service: str, minimum: int, maximum: int) -> appscaling.ScalableTarget:
    return appscaling.scalable_target(
        ServiceNamespace="ecs", ScalableDimension="ecs:service:DesiredCount",
        ResourceId=sub(f"service/${{{cluster}}}/${{{service}.Name}}"), MinCapacity=minimum, MaxCapacity=maximum,
    )


def service_scaling(
    name: str,
    *,
    cluster: str,
    service: str,
    min_capacity: int,
    max_capacity: int,
    cpu_percent: float | None = None,
    memory_percent: float | None = None,
    requests_per_target: tuple[str, str, float] | None = None,
    scale_in_cooldown: int = 300,
    scale_out_cooldown: int = 60,
) -> Resources:
    """`service.autoScaleTaskCount` with `scaleOnCpuUtilization`, `scaleOnMemoryUtilization` and `scaleOnRequestCount`.

    `requests_per_target` is `(load balancer ID, target group ID, requests per task per minute)`. Logical IDs
    are `{name}Target`, `{name}Cpu`, `{name}Memory` and `{name}Requests`. Each is a tracking policy: the
    service adds and removes tasks to keep that average. Scaling in is slower than scaling out, on purpose.
    """
    tracked = [
        ("Cpu", "ECSServiceAverageCPUUtilization", cpu_percent, None),
        ("Memory", "ECSServiceAverageMemoryUtilization", memory_percent, None),
    ]
    if requests_per_target:
        lb, tg, count = requests_per_target
        # the label is the load balancer's and the target group's full names, which Ref and Arn do not give
        label = sub(f"${{{lb}.LoadBalancerFullName}}/${{{tg}.TargetGroupFullName}}")
        tracked.append(("Requests", "ALBRequestCountPerTarget", count, label))
    if all(value is None for _, _, value, _ in tracked):
        raise ValueError("give cpu_percent, memory_percent, requests_per_target or several")
    target = f"{name}Target"
    resources: Resources = {target: _scalable_target(cluster, service, min_capacity, max_capacity)}
    for suffix, metric, value, label in tracked:
        if value is not None:
            spec: appscaling.ScalingPolicyPredefinedMetricSpecification = {"PredefinedMetricType": metric}
            if label:
                spec["ResourceLabel"] = label
            resources[f"{name}{suffix}"] = appscaling.scaling_policy(
                PolicyName=f"{name}{suffix}", PolicyType="TargetTrackingScaling", ScalingTargetId=ref(target),
                TargetTrackingScalingPolicyConfiguration={
                    "TargetValue": value, "PredefinedMetricSpecification": spec,
                    "ScaleInCooldown": scale_in_cooldown, "ScaleOutCooldown": scale_out_cooldown,
                },
            )
    return resources
# --8<-- [end:service_scaling]


# --8<-- [start:queue_step_scaling]
def queue_step_scaling(
    name: str,
    *,
    cluster: str,
    service: str,
    queue: str,
    min_capacity: int,
    max_capacity: int,
    steps: Sequence[tuple[int, int]],
    cooldown: int = 120,
) -> Resources:
    """`scaleOnMetric` with steps: add tasks as the queue grows, and remove one when it is empty.

    `steps` are `(messages waiting, tasks to add)` in ascending order, for example `[(10, 1), (100, 3), (500, 10)]`:
    from 10 messages add one task, from 100 add three, from 500 add ten. The first number is also the alarm's
    threshold. Logical IDs: `{name}Target`, `{name}Out`, `{name}OutAlarm`, `{name}In`, `{name}InAlarm`.
    """
    target, out, into = f"{name}Target", f"{name}Out", f"{name}In"
    threshold = steps[0][0]
    # bounds in a step policy are relative to the alarm's threshold
    adjustments: list[Expr[appscaling.ScalingPolicyStepAdjustment]] = []
    for i, (waiting, add) in enumerate(steps):
        step: appscaling.ScalingPolicyStepAdjustment = {"MetricIntervalLowerBound": waiting - threshold, "ScalingAdjustment": add}
        if i + 1 < len(steps):
            step["MetricIntervalUpperBound"] = steps[i + 1][0] - threshold
        adjustments.append(step)
    backlog = {"QueueName": get_att(queue, "QueueName")}

    def policy(policy_name: str, adjustment_steps: list[Expr[appscaling.ScalingPolicyStepAdjustment]]) -> appscaling.ScalingPolicy:
        return appscaling.scaling_policy(
            PolicyName=policy_name, PolicyType="StepScaling", ScalingTargetId=ref(target),
            StepScalingPolicyConfiguration={
                "AdjustmentType": "ChangeInCapacity", "Cooldown": cooldown,
                "MetricAggregationType": "Maximum", "StepAdjustments": adjustment_steps,
            },
        )

    return {
        target: _scalable_target(cluster, service, min_capacity, max_capacity),
        out: policy(out, adjustments),
        f"{out}Alarm": alarm("AWS/SQS", "ApproximateNumberOfMessagesVisible", dimensions=backlog, threshold=threshold,
                             statistic="Maximum", period=60, actions=[ref(out)]),
        into: policy(into, [{"MetricIntervalUpperBound": 0, "ScalingAdjustment": -1}]),
        f"{into}Alarm": alarm("AWS/SQS", "ApproximateNumberOfMessagesVisible", dimensions=backlog, threshold=0,
                              comparison="LessThanOrEqualToThreshold", statistic="Maximum", period=60,
                              evaluation_periods=10, actions=[ref(into)]),
    }
# --8<-- [end:queue_step_scaling]


# --8<-- [start:lambda_scaling]
def live_alias(name: str, function_logical: str, *, version: str = "1", provisioned: int = 1, alias: str = "live") -> Resources:
    """`fn.addAlias` with provisioned concurrency: `{name}Version{version}` and `{name}Alias`.

    A published version never changes, so a new deploy needs a new logical ID: bump `version` (the CDK uses a hash
    of the code). The old version is then deleted, and the alias moves to the new one.
    """
    ver = f"{name}Version{version}"
    return {
        ver: lambda_.version(FunctionName=ref(function_logical)),
        f"{name}Alias": lambda_.alias(
            FunctionName=ref(function_logical), Name=alias, FunctionVersion=get_att(ver, "Version"),
            ProvisionedConcurrencyConfig={"ProvisionedConcurrentExecutions": provisioned},
        ),
    }


def lambda_scaling(
    name: str,
    *,
    function_logical: str,
    alias_logical: str,
    alias: str = "live",
    min_capacity: int,
    max_capacity: int,
    utilization: float = 0.7,
) -> Resources:
    """`alias.addAutoScaling`: keep provisioned concurrency about `utilization` busy. Logical IDs `{name}Target`, `{name}Tracking`."""
    target = f"{name}Target"
    return {
        target: appscaling.scalable_target(
            ServiceNamespace="lambda", ScalableDimension="lambda:function:ProvisionedConcurrency",
            ResourceId=sub(f"function:${{{function_logical}}}:{alias}"), MinCapacity=min_capacity, MaxCapacity=max_capacity,
            depends_on=alias_logical,  # the alias is what carries the provisioned concurrency
        ),
        f"{name}Tracking": appscaling.scaling_policy(
            PolicyName=f"{name}Tracking", PolicyType="TargetTrackingScaling", ScalingTargetId=ref(target),
            TargetTrackingScalingPolicyConfiguration={
                "TargetValue": utilization,
                "PredefinedMetricSpecification": {"PredefinedMetricType": "LambdaProvisionedConcurrencyUtilization"},
            },
        ),
    }
# --8<-- [end:lambda_scaling]


# --8<-- [start:table_scaling]
def table_scaling(
    name: str,
    *,
    table: str,
    read: tuple[int, int] | None = None,
    write: tuple[int, int] | None = None,
    utilization: float = 70,
) -> Resources:
    """`table.autoScaleReadCapacity` and `autoScaleWriteCapacity`: `read` and `write` are `(min, max)` units.

    Only for a table with `BillingMode: PROVISIONED`: an on-demand table, which is what the storage pattern makes,
    already scales by itself and has nothing to register. Logical IDs `{name}ReadTarget`, `{name}ReadTracking`,
    `{name}WriteTarget`, `{name}WriteTracking`.
    """
    resources: Resources = {}
    for kind, limits in (("Read", read), ("Write", write)):
        if limits is None:
            continue
        target = f"{name}{kind}Target"
        resources[target] = appscaling.scalable_target(
            ServiceNamespace="dynamodb", ScalableDimension=f"dynamodb:table:{kind}CapacityUnits",
            ResourceId=sub(f"table/${{{table}}}"), MinCapacity=limits[0], MaxCapacity=limits[1],
        )
        resources[f"{name}{kind}Tracking"] = appscaling.scaling_policy(
            PolicyName=f"{name}{kind}Tracking", PolicyType="TargetTrackingScaling", ScalingTargetId=ref(target),
            TargetTrackingScalingPolicyConfiguration={
                "TargetValue": utilization,
                "PredefinedMetricSpecification": {"PredefinedMetricType": f"DynamoDB{kind}CapacityUtilization"},
            },
        )
    return resources
# --8<-- [end:table_scaling]
