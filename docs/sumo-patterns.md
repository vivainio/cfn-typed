# Sumo patterns

Every pattern in `cfn-typed-sumo`, with a link to its code and the resources it creates. Each is an ordinary
function that returns a resource or a `Resources` fragment (some return a small handle with the logical IDs and
references); combine fragments with [`combine`](patterns/composing.md). The link on each name goes to its source on GitHub.

The patterns are opinions and the API is volatile: see [cfn-typed-sumo](sumo.md). Import the ones in the
first three sections from the package (`from cfn_typed_sumo import queue_with_dlq`), and the others from their
module (`from cfn_typed_sumo.storage import secure_bucket`).

## Basics: roles, queues, tags and rules

`cfn_typed_sumo.patterns`

| Pattern | What it is | Resources | Book |
|---|---|---|---|
| [`lambda_role`](https://github.com/vivainio/cfn-typed/blob/main/packages/sumo/src/cfn_typed_sumo/patterns.py#L21) | Execution role for a Lambda: log permissions plus the `extra` statements. | `IAM::Role` with log permissions plus your statements | [page](patterns/lambda-role.md) |
| [`sqs_event_source`](https://github.com/vivainio/cfn-typed/blob/main/packages/sumo/src/cfn_typed_sumo/patterns.py#L38) | Trigger the Lambda `function_logical` from an SQS queue. | `Lambda::EventSourceMapping` | [page](patterns/sqs-trigger.md) |
| [`queue_with_dlq`](https://github.com/vivainio/cfn-typed/blob/main/packages/sumo/src/cfn_typed_sumo/patterns.py#L70) | A queue and its dead-letter queue, with logical IDs `{name}Queue` and `{name}DLQ`. | 2 × `SQS::Queue` (queue and dead-letter queue); a handle with ARNs and URLs | [page](patterns/queue-with-dlq.md) |
| [`tagged`](https://github.com/vivainio/cfn-typed/blob/main/packages/sumo/src/cfn_typed_sumo/patterns.py#L123) | Resolve the company tags for every taggable resource: its own tags over the `service` tags. | no resources: resolves the mandatory company tags onto the template's resources | [page](patterns/mandatory-tags.md) |
| [`untagged`](https://github.com/vivainio/cfn-typed/blob/main/packages/sumo/src/cfn_typed_sumo/patterns.py#L144) | Logical IDs of taggable resources missing a company tag: a backstop for templates that skip `tagged`. | no resources: lists taggable resources missing a company tag | [page](patterns/mandatory-tags.md) |
| [`COMPANY_RULES`](https://github.com/vivainio/cfn-typed/blob/main/packages/sumo/src/cfn_typed_sumo/patterns.py#L187) | The company's rules as `Rule` functions: S3 encryption and public access, log retention, no admin policies, queue naming, dead-letter queues. | no resources: rules for `assert_template_ok(..., rules=)` | [page](patterns/company-rules.md) |

## HTTP API

`cfn_typed_sumo.http_api`

| Pattern | What it is | Resources | Book |
|---|---|---|---|
| [`http_api`](https://github.com/vivainio/cfn-typed/blob/main/packages/sumo/src/cfn_typed_sumo/http_api.py#L49) | An HTTP API sending every route in `routes` (e.g. `"GET /orders"`) to the Lambda `function` (a logical ID). | `ApiGatewayV2::Api`, `Integration`, `Stage`, `Authorizer` (with `jwt`), one `Route` per route key, `Lambda::Permission` | [page](patterns/http-api.md) |

## Static site

`cfn_typed_sumo.static_site`

| Pattern | What it is | Resources | Book |
|---|---|---|---|
| [`static_site`](https://github.com/vivainio/cfn-typed/blob/main/packages/sumo/src/cfn_typed_sumo/static_site.py#L36) | A private bucket served by CloudFront through origin access control (OAC). | `S3::Bucket` + `BucketPolicy`, `CloudFront::OriginAccessControl` + `Distribution`; with a domain `CertificateManager::Certificate` | [page](patterns/web-frontends.md) |

## Load balancers

`cfn_typed_sumo.loadbalancer`

| Pattern | What it is | Resources | Book |
|---|---|---|---|
| [`load_balancer`](https://github.com/vivainio/cfn-typed/blob/main/packages/sumo/src/cfn_typed_sumo/loadbalancer.py#L16) | An application load balancer. No `Name`, so CloudFormation picks a unique one. | `ElasticLoadBalancingV2::LoadBalancer` | [page](patterns/load-balancer.md) |
| [`target_group`](https://github.com/vivainio/cfn-typed/blob/main/packages/sumo/src/cfn_typed_sumo/loadbalancer.py#L39) | Where the traffic goes. A short deregistration delay makes deploys faster. | `ElasticLoadBalancingV2::TargetGroup` | [page](patterns/load-balancer.md) |
| [`listener`](https://github.com/vivainio/cfn-typed/blob/main/packages/sumo/src/cfn_typed_sumo/loadbalancer.py#L71) | Forward a port to a target group. A certificate turns it into an HTTPS listener. | `ElasticLoadBalancingV2::Listener` (HTTPS with a certificate) | [page](patterns/load-balancer.md) |
| [`redirect_http_to_https`](https://github.com/vivainio/cfn-typed/blob/main/packages/sumo/src/cfn_typed_sumo/loadbalancer.py#L91) | A listener that answers with a permanent redirect instead of forwarding. | `ElasticLoadBalancingV2::Listener` | [page](patterns/load-balancer.md) |
| [`allow_from`](https://github.com/vivainio/cfn-typed/blob/main/packages/sumo/src/cfn_typed_sumo/loadbalancer.py#L106) | Let `source_group` (the load balancer's) reach `group` (the instances') on `port`. | `EC2::SecurityGroupIngress` | [page](patterns/load-balancer.md) |
| [`web_entrypoint`](https://github.com/vivainio/cfn-typed/blob/main/packages/sumo/src/cfn_typed_sumo/loadbalancer.py#L119) | One load balancer in front of several ports. | `EC2::SecurityGroup`, `LoadBalancer`, and a `TargetGroup` and `Listener` per port | [page](patterns/web-entrypoint.md) |

## Storage

`cfn_typed_sumo.storage`

| Pattern | What it is | Resources | Book |
|---|---|---|---|
| [`encryption_key`](https://github.com/vivainio/cfn-typed/blob/main/packages/sumo/src/cfn_typed_sumo/storage.py#L18) | A KMS key with rotation and an alias: logical IDs `{name}Key` and `{name}KeyAlias`. | `KMS::Key` + `KMS::Alias` | [page](patterns/storage.md) |
| [`secure_bucket`](https://github.com/vivainio/cfn-typed/blob/main/packages/sumo/src/cfn_typed_sumo/storage.py#L48) | A private, encrypted bucket and its policy: logical IDs `{name}Bucket` and `{name}BucketPolicy`. | `S3::Bucket` + `S3::BucketPolicy` | [page](patterns/storage.md) |
| [`dynamodb_table`](https://github.com/vivainio/cfn-typed/blob/main/packages/sumo/src/cfn_typed_sumo/storage.py#L99) | An on-demand table with point-in-time recovery. Keys are `"name"` (a string) or `("name", "N")`. | `DynamoDB::Table` | [page](patterns/storage.md) |
| [`ecr_repository`](https://github.com/vivainio/cfn-typed/blob/main/packages/sumo/src/cfn_typed_sumo/storage.py#L120) | A repository with immutable tags and scan-on-push, that the given principals may pull from. | `ECR::Repository` | [page](patterns/storage.md) |
| [`publish`](https://github.com/vivainio/cfn-typed/blob/main/packages/sumo/src/cfn_typed_sumo/storage.py#L148) | Publish values as SSM parameters named `{prefix}/{key}`, for other stacks to read. | one `SSM::Parameter` per value | [page](patterns/publishing.md) |

## Compute, network and scaling (CDK L2 style)

`cfn_typed_sumo.constructs`

| Pattern | What it is | Resources | Book |
|---|---|---|---|
| [`function`](https://github.com/vivainio/cfn-typed/blob/main/packages/sumo/src/cfn_typed_sumo/constructs.py#L39) | `lambda.Function`: the function, its execution role and its log group, `{name}`, `{name}Role` and `{name}Logs`. | `Lambda::Function`, `IAM::Role`, `Logs::LogGroup` | [page](patterns/serverless.md) |
| [`invoke_permission`](https://github.com/vivainio/cfn-typed/blob/main/packages/sumo/src/cfn_typed_sumo/constructs.py#L85) | `grantInvoke` for a service: let `principal` (`"events.amazonaws.com"`) invoke the function, from `source_arn` only. | `Lambda::Permission` | [page](patterns/cdk-l2.md) |
| [`schedule`](https://github.com/vivainio/cfn-typed/blob/main/packages/sumo/src/cfn_typed_sumo/constructs.py#L97) | `events.Rule` with a `LambdaFunction` target: the rule and the permission it needs, `{name}Rule`, `{name}Permission`. | `Events::Rule` + `Lambda::Permission` | [page](patterns/serverless.md) |
| [`topic_to_queue`](https://github.com/vivainio/cfn-typed/blob/main/packages/sumo/src/cfn_typed_sumo/constructs.py#L116) | `SqsSubscription`: one subscription per topic, and the one queue policy that lets them all send. | one `SNS::Subscription` per topic + one `SQS::QueuePolicy` | [page](patterns/messaging.md) |
| [`vpc`](https://github.com/vivainio/cfn-typed/blob/main/packages/sumo/src/cfn_typed_sumo/constructs.py#L173) | `ec2.Vpc`: public and private subnets in `zones` availability zones, an internet gateway, and a NAT gateway per zone. | `EC2::VPC`, internet gateway, subnets per zone (public and private), route tables, NAT gateways with `EIP`s | [page](patterns/cdk-l2.md) |
| [`fargate_service`](https://github.com/vivainio/cfn-typed/blob/main/packages/sumo/src/cfn_typed_sumo/constructs.py#L236) | `ApplicationLoadBalancedFargateService`: a cluster, a task, a service and an internet-facing load balancer. | `ECS::Cluster`, `TaskDefinition`, `Service`, load balancer with target group and listener, 2 × `SecurityGroup`, 2 × `IAM::Role`, `Logs::LogGroup` | [page](patterns/containers.md) |
| [`alarm`](https://github.com/vivainio/cfn-typed/blob/main/packages/sumo/src/cfn_typed_sumo/constructs.py#L321) | `metric.createAlarm`: one alarm on one metric. `actions` run when it fires, `ok_actions` when it recovers. | `CloudWatch::Alarm` | [page](patterns/cdk-l2.md) |
| [`queue_backlog_alarm`](https://github.com/vivainio/cfn-typed/blob/main/packages/sumo/src/cfn_typed_sumo/constructs.py#L361) | `queue.metricApproximateNumberOfMessagesVisible().createAlarm`: too many messages waiting for `minutes`. | `CloudWatch::Alarm` | [page](patterns/cdk-l2.md) |
| [`lambda_errors_alarm`](https://github.com/vivainio/cfn-typed/blob/main/packages/sumo/src/cfn_typed_sumo/constructs.py#L370) | `fn.metricErrors().createAlarm`: the function failed at least `threshold` times in a minute. | `CloudWatch::Alarm` | [page](patterns/cdk-l2.md) |
| [`alarm_topic`](https://github.com/vivainio/cfn-typed/blob/main/packages/sumo/src/cfn_typed_sumo/constructs.py#L378) | A topic for alarms to notify, with an email subscription each: `{name}Topic` and `{name}Email{n}`. | `SNS::Topic` + one email `SNS::Subscription` each | [page](patterns/cdk-l2.md) |
| [`composite_alarm`](https://github.com/vivainio/cfn-typed/blob/main/packages/sumo/src/cfn_typed_sumo/constructs.py#L389) | `CompositeAlarm.fromAlarms`: fires when `any` or `all` of the alarms with these logical IDs are in `ALARM`. | `CloudWatch::CompositeAlarm` | [page](patterns/cdk-l2.md) |
| [`service_scaling`](https://github.com/vivainio/cfn-typed/blob/main/packages/sumo/src/cfn_typed_sumo/constructs.py#L420) | `service.autoScaleTaskCount` with `scaleOnCpuUtilization`, `scaleOnMemoryUtilization` and `scaleOnRequestCount`. | `ApplicationAutoScaling::ScalableTarget` + `ScalingPolicy` | [page](patterns/cdk-l2.md) |
| [`queue_step_scaling`](https://github.com/vivainio/cfn-typed/blob/main/packages/sumo/src/cfn_typed_sumo/constructs.py#L469) | `scaleOnMetric` with steps: add tasks as the queue grows, and remove one when it is empty. | `ScalableTarget`, 2 × `ScalingPolicy`, 2 × `CloudWatch::Alarm` | [page](patterns/cdk-l2.md) |
| [`live_alias`](https://github.com/vivainio/cfn-typed/blob/main/packages/sumo/src/cfn_typed_sumo/constructs.py#L520) | `fn.addAlias` with provisioned concurrency: `{name}Version{version}` and `{name}Alias`. | `Lambda::Version` + `Lambda::Alias` | [page](patterns/serverless.md) |
| [`lambda_scaling`](https://github.com/vivainio/cfn-typed/blob/main/packages/sumo/src/cfn_typed_sumo/constructs.py#L536) | `alias.addAutoScaling`: keep provisioned concurrency about `utilization` busy. Logical IDs `{name}Target`, `{name}Tracking`. | `ApplicationAutoScaling::ScalableTarget` + `ScalingPolicy` | [page](patterns/cdk-l2.md) |
| [`table_scaling`](https://github.com/vivainio/cfn-typed/blob/main/packages/sumo/src/cfn_typed_sumo/constructs.py#L566) | `table.autoScaleReadCapacity` and `autoScaleWriteCapacity`: `read` and `write` are `(min, max)` units. | `ScalableTarget` + `ScalingPolicy` for each of read and write | [page](patterns/cdk-l2.md) |

## Integrations: A connected to B

`cfn_typed_sumo.integrations`

| Pattern | What it is | Resources | Book |
|---|---|---|---|
| [`api_to_lambda`](https://github.com/vivainio/cfn-typed/blob/main/packages/sumo/src/cfn_typed_sumo/integrations.py#L51) | A REST API that proxies every path and method to a Lambda function. | `ApiGateway::RestApi`, `Resource`, 2 × `Method`, `Deployment`, `Stage`, `Lambda::Permission` | [page](patterns/web-frontends.md) |
| [`api_to_dynamodb`](https://github.com/vivainio/cfn-typed/blob/main/packages/sumo/src/cfn_typed_sumo/integrations.py#L87) | `GET /items/{id}` straight from a table, with no Lambda in between. | `ApiGateway::RestApi`, 2 × `Resource`, `Method`, `Deployment`, `Stage`, `IAM::Role` | [page](patterns/web-frontends.md) |
| [`lambda_behind_alb`](https://github.com/vivainio/cfn-typed/blob/main/packages/sumo/src/cfn_typed_sumo/integrations.py#L126) | Send the requests that match `path_pattern` on an existing listener to a Lambda function. | `ElasticLoadBalancingV2::TargetGroup` + `ListenerRule`, `Lambda::Permission` | [page](patterns/web-frontends.md) |
| [`alias_to_load_balancer`](https://github.com/vivainio/cfn-typed/blob/main/packages/sumo/src/cfn_typed_sumo/integrations.py#L170) | An A record in `zone_id` that points at a load balancer in this template. | `Route53::RecordSet` | [page](patterns/web-frontends.md) |
| [`alias_to_distribution`](https://github.com/vivainio/cfn-typed/blob/main/packages/sumo/src/cfn_typed_sumo/integrations.py#L184) | An A record in `zone_id` that points at a CloudFront distribution in this template. | `Route53::RecordSet` | [page](patterns/web-frontends.md) |
| [`fan_out`](https://github.com/vivainio/cfn-typed/blob/main/packages/sumo/src/cfn_typed_sumo/integrations.py#L205) | One topic, and for each subscriber its own queue with a dead-letter queue. | `SNS::Topic`; per subscriber a queue, a dead-letter queue, a `QueuePolicy` and a `Subscription` | [page](patterns/messaging.md) |
| [`event_to_lambda`](https://github.com/vivainio/cfn-typed/blob/main/packages/sumo/src/cfn_typed_sumo/integrations.py#L235) | An EventBridge rule that invokes a Lambda: `{name}Rule` and `{name}InvokePermission`. | `Events::Rule` + `Lambda::Permission` | [page](patterns/messaging.md) |
| [`event_to_queue`](https://github.com/vivainio/cfn-typed/blob/main/packages/sumo/src/cfn_typed_sumo/integrations.py#L255) | An EventBridge rule that sends to an SQS queue: `{name}Rule` and `{name}Policy`. | `Events::Rule` + `SQS::QueuePolicy` | [page](patterns/messaging.md) |
| [`stream_trigger`](https://github.com/vivainio/cfn-typed/blob/main/packages/sumo/src/cfn_typed_sumo/integrations.py#L292) | Invoke a Lambda for the changes of a DynamoDB table: `{name}StreamMapping`. | `Lambda::EventSourceMapping`, and the statements the role needs | [page](patterns/data-flows.md) |
| [`with_stream`](https://github.com/vivainio/cfn-typed/blob/main/packages/sumo/src/cfn_typed_sumo/integrations.py#L325) | The same table with a stream. The table is not modified. | the same `DynamoDB::Table`, with a stream | [page](patterns/data-flows.md) |
| [`bucket_to_lambda`](https://github.com/vivainio/cfn-typed/blob/main/packages/sumo/src/cfn_typed_sumo/integrations.py#L332) | A private bucket that invokes a Lambda when objects arrive: `{name}Bucket` and `{name}InvokePermission`. | `S3::Bucket` with a notification, `Lambda::Permission` | [page](patterns/data-flows.md) |
| [`firehose_to_s3`](https://github.com/vivainio/cfn-typed/blob/main/packages/sumo/src/cfn_typed_sumo/integrations.py#L376) | A Firehose delivery stream that writes GZIP files to a bucket, with its role and logs. | `KinesisFirehose::DeliveryStream`, `IAM::Role`, `Logs::LogGroup` + `LogStream` | [page](patterns/data-flows.md) |
| [`fargate_task`](https://github.com/vivainio/cfn-typed/blob/main/packages/sumo/src/cfn_typed_sumo/integrations.py#L467) | A cluster, a task definition and (with `desired_count`) a service running one container, with no load balancer. | `ECS::Cluster`, `TaskDefinition`, `Service` (optional), 2 × `IAM::Role`, `Logs::LogGroup` | [page](patterns/containers.md) |
