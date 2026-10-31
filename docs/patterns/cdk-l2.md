# CDK L2 constructs as patterns

The AWS CDK's L2 constructs are the best-known set of "what a sensible resource looks like". Each one does three
things: it picks defaults, it creates the helper resources that always go with the main one, and it wires them
together. A pattern does the same three things as an ordinary function, and shows its work.

This page rebuilds ten of them. Every snippet is pulled from
[`packages/sumo/src/cfn_typed_sumo/constructs.py`](https://github.com/vivainio/cfn-typed/blob/main/packages/sumo/src/cfn_typed_sumo/constructs.py), which is
type-checked and tested like the other patterns.

```python
--8<-- "packages/sumo/src/cfn_typed_sumo/constructs.py:imports"
```

| CDK construct | Pattern | Creates |
|---|---|---|
| `lambda.Function` | `function` | function, execution role, log group with retention |
| `events.Rule` + `LambdaFunction` target | `schedule` | the rule and the invoke permission |
| `sns.Topic` + `SqsSubscription` | `topic_to_queue` | subscriptions and the one queue policy |
| `ec2.Vpc` | `vpc` | subnets, gateway, routes and NAT per availability zone |
| `ApplicationLoadBalancedFargateService` | `fargate_service` | cluster, task, service, load balancer, security groups |
| `metric.createAlarm` | `alarm`, `queue_backlog_alarm`, `lambda_errors_alarm`, `alarm_topic` | an alarm, or a topic with email subscriptions |
| `CompositeAlarm.fromAlarms` | `composite_alarm` | one alarm over several |
| `service.autoScaleTaskCount` | `service_scaling`, `queue_step_scaling` | a scalable target and its policies, and alarms for step scaling |
| `fn.addAlias` with `addAutoScaling` | `live_alias`, `lambda_scaling` | a version, an alias with provisioned concurrency, and its scaling |
| `table.autoScaleReadCapacity` | `table_scaling` | scalable targets and tracking policies for a provisioned table |

## What an L2 does that a pattern has to spell out

| In the CDK | In a pattern |
|---|---|
| A role is created implicitly | a second resource in the fragment, with a logical ID derived from `name` |
| `grantInvoke`, `addToRolePolicy` mutate an object | a function that returns the statement or resource, or an argument such as `statements` |
| Defaults live in the class | defaults live in the signature, and optional pieces are emitted only when given |
| The construct tree names things | the call documents the logical IDs, and a handle exposes them |

## `lambda.Function`

```python
--8<-- "packages/sumo/src/cfn_typed_sumo/constructs.py:function"
```

The CDK function carries a role and, with a retention setting, a log group. Here both are in the fragment, and
the function points at the log group through `LoggingConfig`, so Lambda never creates one that would live forever.
`statements` takes the same statements as [grants](../grants.md), so
`statements=grants.Sqs.Queue.consume_messages.on(orders.queue_arn)` is the equivalent of `queue.grantConsumeMessages(fn)`.

## `events.Rule` with a Lambda target

```python
--8<-- "packages/sumo/src/cfn_typed_sumo/constructs.py:invoke_permission"
--8<-- "packages/sumo/src/cfn_typed_sumo/constructs.py:schedule"
```

The CDK's `LambdaFunction` target adds the permission for you, and forgetting it in plain CloudFormation is a
classic silent failure: the rule fires and nothing runs. Putting the rule and the permission in one fragment makes
the mistake impossible. `invoke_permission` is its own function because the same thing is needed for S3, SNS and
API Gateway, with another principal.

## `sns.Topic` with an SQS subscription

```python
--8<-- "packages/sumo/src/cfn_typed_sumo/constructs.py:topic_to_queue"
```

This is the one place where the construct model and the pattern model differ. `topic.addSubscription(...)` edits the
queue's policy, and a second call edits it again. A pattern has no object to edit, and two `QueuePolicy` resources
for one queue overwrite each other. The fix is to make the topics the argument: **a pattern that needs to merge
state takes all the inputs in one call.**

## `ec2.Vpc`

```python
--8<-- "packages/sumo/src/cfn_typed_sumo/constructs.py:vpc"
```

A VPC is where the plain-Python approach pays off: the CDK needs an internal subnet-allocation engine, and here it
is a `for` loop and `Fn::Cidr`. The handle gives `vpc_id`, `public_subnet_ids` and `private_subnet_ids`, which is
what the next pattern wants. `nat_gateways=False` skips the NAT gateways and their addresses, which are the
expensive part.

## `ApplicationLoadBalancedFargateService`

This one is an L3 in the CDK's own terms, and it is the most useful example because it is built from the other
patterns: the [load balancer building blocks](load-balancer.md) are reused as they are.

```python
--8<-- "packages/sumo/src/cfn_typed_sumo/constructs.py:fargate_service"
```

Used together with the VPC:

```python
net = vpc("Net")
web = fargate_service(
    "Web",
    vpc_id=net.vpc_id,
    public_subnets=net.public_subnet_ids,
    private_subnets=net.private_subnet_ids,
    image="public.ecr.aws/nginx/nginx:stable",
    statements=grants.S3.Bucket.read.on(bucket_arn),
)
template: cfn.Template = {"Resources": cfn.combine(net, web), "Outputs": {"Url": {"Value": web.dns_name}}}
```

Things worth noticing:

- **`target_type="ip"`** is required for Fargate and is easy to forget, because the building block defaults to
  instances.
- **`depends_on=lis`** on the service is the CDK's implicit ordering made explicit: the target group is not attached
  to a load balancer until a listener exists, and a service created before that fails.
- **Two roles**, as in the CDK: the execution role pulls the image and writes logs, the task role is what your code
  runs as and is the one that takes `statements`.
- **`cfn.combine(net, web)`** accepts the handles directly and fails on a logical ID clash.

## `metric.createAlarm`

```python
--8<-- "packages/sumo/src/cfn_typed_sumo/constructs.py:alarm"
```

```python
--8<-- "packages/sumo/src/cfn_typed_sumo/constructs.py:alarm_helpers"
```

An alarm is one resource, so the value is in the defaults and in the shortcuts. `queue_backlog_alarm` and
`lambda_errors_alarm` are what the CDK spells `queue.metricApproximateNumberOfMessagesVisible().createAlarm(...)`: they
know the namespace, metric name and dimension, which are the parts you would otherwise look up every time.

```python
alerts = alarm_topic("Ops", ["oncall@example.com"])
cfn.combine(
    alerts,
    {"BacklogAlarm": queue_backlog_alarm("OrderQueue", threshold=500, actions=[cfn.ref("OpsTopic")])},
)
```

- **`actions` and `ok_actions` are separate.** The helpers send both to the same topic, so people hear when it is
  over. A scaling alarm must not do that: an `OK` that triggered a scale-out policy would grow the service when the
  queue recovers. The CDK keeps the two apart for the same reason.
- **Missing data does not breach.** An error count is only published when there is an error, so counting a gap as
  a breach would leave the alarm stuck.

### Composite alarms

```python
--8<-- "packages/sumo/src/cfn_typed_sumo/constructs.py:composite_alarm"
```

```python
cfn.combine(
    {"Backlog": queue_backlog_alarm("OrderQueue", threshold=500),
     "Errors": lambda_errors_alarm("Processor")},
    {"PageOncall": composite_alarm("PageOncall", ["Backlog", "Errors"], actions=[cfn.ref("OpsTopic")])},
)
```

The two inner alarms have no actions, so they only change state. Only the composite notifies anyone, and only when both
are firing. Note that the alarms are named by logical ID and the rule is built from their ARNs, so the composite
cannot be created before them.

## `service.autoScaleTaskCount`

Auto scaling has two flavours, and they differ in who does the arithmetic.

```python
--8<-- "packages/sumo/src/cfn_typed_sumo/constructs.py:service_scaling"
```

**Target tracking** (`scaleOnCpuUtilization`) is one policy: say what the average should be, and the service adds
and removes tasks to hold it. It needs no alarms of its own, since Application Auto Scaling creates them. Pass the
logical IDs of the cluster and the service from `fargate_service`:

```python
service_scaling("Web", cluster="WebCluster", service="WebService", min_capacity=2, max_capacity=10, cpu_percent=60)
```

The scalable target's `ResourceId` is built with `Fn::Sub` from the two IDs, so the template depends on both and
no one has to type `service/cluster/service`.

**Request count** is the third built-in, and the one that suits a web service best: CPU says the tasks are busy,
requests per task says why.

```python
service_scaling("Web", cluster="WebCluster", service="WebService", min_capacity=2, max_capacity=10,
                cpu_percent=60, requests_per_target=("WebLoadBalancer", "WebTargetGroup", 1000))
```

The policy needs a *resource label*, the load balancer's and the target group's **full names** joined with a slash
(`app/web/50dc.../targetgroup/web/6d0e...`). Neither `Ref` nor `Arn` is that; the attributes are
`LoadBalancerFullName` and `TargetGroupFullName`, so the label is an `Fn::Sub` over them. It is the kind of detail
you would otherwise find by trial and error, and now it is in one place. Several kinds can be given together, and
the service follows whichever asks for the most tasks.

**Step scaling** is the one you write when the metric is not a built-in average, such as the depth of a queue. It is
where alarms and scaling meet, and what the CDK's `scaleOnMetric` builds:

```python
--8<-- "packages/sumo/src/cfn_typed_sumo/constructs.py:queue_step_scaling"
```

```python
queue_step_scaling("Work", cluster="WorkCluster", service="WorkService", queue="OrderQueue",
                   min_capacity=1, max_capacity=20, steps=[(10, 1), (100, 3), (500, 10)])
```

- **Step bounds are relative to the alarm.** CloudWatch passes the policy the distance past the threshold, not the
  metric. With a threshold of 10, "from 100 messages" is a lower bound of 90. The function does that subtraction, so
  the call reads as the numbers you mean.
- **The alarms only act on `ALARM`.** There is no `ok_actions` here, for the reason above.
- **Scale-in is deliberately blunt.** One task is removed after ten empty minutes. Tune it, or copy the function and
  replace the second half, which is the point of having it as ordinary code.

## Provisioned concurrency for a Lambda

```python
--8<-- "packages/sumo/src/cfn_typed_sumo/constructs.py:lambda_scaling"
```

```python
job = function("Job", code=code, handler="index.handler", runtime="python3.13")
cfn.combine(
    job,
    live_alias("Job", "Job", version="1", provisioned=2),
    lambda_scaling("Job", function_logical="Job", alias_logical="JobAlias", min_capacity=2, max_capacity=50),
)
```

Scaling applies to an *alias*, not to the function, so a version and an alias come first. Two things to know:

- **A version is immutable.** CloudFormation will not update `AWS::Lambda::Version` in place, so shipping new code
  means a new logical ID. The CDK hashes the code to get one. Here it is the `version` argument: the honest cost
  of having no hidden state, and an easy thing to wire to a build number.
- **The scalable target depends on the alias**, since that is where the provisioned concurrency lives. Without
  `depends_on` the registration can run first and fail.

## `table.autoScaleReadCapacity`

```python
--8<-- "packages/sumo/src/cfn_typed_sumo/constructs.py:table_scaling"
```

```python
table_scaling("Orders", table="OrdersTable", read=(5, 50), write=(5, 200))
```

This is one to read before you copy: the [storage pattern](storage.md) makes **on-demand** tables, which scale by
themselves and have nothing to register, so scaling only applies to a table that you create as
`BillingMode: PROVISIONED`. It is here because that is when you need it, and because read and write use the same
shape with a different dimension and metric name, which is what the loop is for.

## Where a pattern is not an L2

A pattern is a function, so it is not a type you can pass around and call methods on. There is no `bucket.grantRead(role)`
that reaches into an object: the same effect is a statement from [grants](../grants.md) given to whatever needs it.
The trade is a longer call at the use site, in return for a template where every resource, and the reason for it,
can be read in the function that made it.
