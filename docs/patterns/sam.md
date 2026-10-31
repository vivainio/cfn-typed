# AWS SAM

AWS SAM is a CloudFormation transform: a template with `Transform: AWS::Serverless-2016-10-31` may use
`AWS::Serverless::Function`, `Api`, `HttpApi`, `SimpleTable`, `StateMachine` and a few more, which CloudFormation
expands into plain resources when you deploy. The types are generated like the rest, from SAM's own schema at a
[pinned release](../generator.md#aws-sam-types), and live in `cfn_typed_sumo.types.serverless`.

```python
import cfn_typed as cfn
from cfn_typed_sumo import sam
from cfn_typed_sumo.types import serverless, sqs


def build() -> cfn.Template:
    orders = sqs.queue()
    worker = serverless.function(
        Handler="app.handler",
        CodeUri="src/",
        Events={
            "Orders": sam.sqs_event(cfn.get_att("Orders", "Arn"), max_batching_window=5),
            "Web": sam.http_api_event("/orders", "POST"),
        },
    )
    return sam.template(
        {"Orders": orders, "Worker": worker},
        function_globals={"Runtime": "python3.12", "Timeout": 30, "MemorySize": 512},
    )
```

`sam.template` writes the `Transform` header and `Globals`; SAM merges `Globals` into every function, so the runtime
and timeout are stated once. Property names are checked as for any generated type: `serverless.function(Handlr=...)`
is an error, and so is a wrong type for `Handler`.

## Functions, tables and connectors

`serverless.function` takes SAM's property names. `sam.function` takes the arguments the other patterns use, and
leaves `Runtime`, `MemorySize` and `Timeout` to `Globals` unless you pass them:

```python
worker = sam.function(
    handler="app.handler",
    code_uri="src/",
    events={"Orders": sam.sqs_event(cfn.get_att("Orders", "Arn"))},
    environment={"TABLE": cfn.ref("Table")},
    statements=[cfn.allow("dynamodb:GetItem", cfn.get_att("Table", "Arn"))],   # one inline policy, as in grants
    managed_policies=["AWSLambdaBasicExecutionRole"],
)
```

| Pattern | Resource | Notes |
|---|---|---|
| `table(key, key_type="String")` | `StateMachine` (`Definition`, `Policies`, `Schedule` and `EventBridgeRule` events) | `StepFunctions::StateMachine`, its `{Name}Role`, and for each event the rule and a role that may start the execution |
| `SimpleTable` | one partition key |
| `connect(name, source, destination, permissions=("Read",))` | `Connector`, or `Connectors` inside a function | SAM writes the least-privilege policy for the pair; the ID is `{name}Connector` |

`connect` replaces a hand-written role statement when both ends are in the template. For anything it cannot say
(conditions, a resource outside the template), use `statements=` instead.

## What the event builders do

An event is a small typed dict. The builders exist because of two things the checker cannot do for an inline dict:

| Builder | Event | What SAM creates |
|---|---|---|
| `sqs_event(queue_arn, batch_size=10)` | `SQS` | the event source mapping and read access to the queue |
| `http_api_event(path, method)` | `HttpApi` | a route on the implicit HTTP API (or `api_id`'s) |
| `schedule_event(expression)` | `Schedule` | the rule and the permission to invoke the function |
| `sns_event(topic)` | `SNS` | the subscription and the permission for the topic to invoke the function |
| `stream_event("Kinesis" or "DynamoDB", stream_arn)` | `Kinesis`, `DynamoDB` | the event source mapping and read access to the stream |
| `event_bridge_event(pattern)` | `EventBridgeRule` | a rule on the default bus and the permission to invoke |

For any other event type, build it as a typed value first (`e: serverless.FunctionS3Event = {...}`) and pass that in
`Events`.

## SAM or the patterns

SAM does the packaging side that [patterns](serverless.md) leave out (`sam build`, `sam package` upload the code and
fill in `CodeUri`), and it expands to resources you do not see until deploy. Use SAM types when you want that
workflow with checked properties. Use the plain `function` pattern when you want the exact resources in the
template, as for the [Serverless Framework](serverless.md#moving-an-existing-service) migration, with logical IDs you choose.

## SAM without SAM: `expand`

`sam.expand(template)` does the transform in Python. It takes a template of `serverless.*` resources (and `Globals`)
and returns plain CloudFormation: no `Transform`, no `Globals`, and no mention of SAM anywhere in it. The function,
its role, the event source mappings, rules and routes are ordinary resources you can read, diff and check before
you deploy, and the stack deploys in an account or pipeline where transforms are not allowed.

```python
from cfn_typed_sumo import sam

template = sam.expand(build())   # build() returns the SAM template from above
```

It covers a fixed subset, the SAM release the types are pinned to, and says so when you go outside it:

| SAM | Becomes |
|---|---|
| `Function` (S3 `CodeUri`, `Environment`, `Policies`, `Tags`, ...) | `Lambda::Function` and `IAM::Role` (`{Name}`, `{Name}Role`) |
| `SQS`, `Kinesis`, `DynamoDB` event | `Lambda::EventSourceMapping` `{Name}{Event}`, and the matching execution policy on the role |
| `SNS` event | `SNS::Subscription` `{Name}{Event}` and `Lambda::Permission` `{Name}{Event}Permission` |
| `Schedule`, `EventBridgeRule` event | `Events::Rule` `{Name}{Event}` and `Lambda::Permission` `{Name}{Event}Permission` |
| `Api` event (REST) | `ApiGateway` `RestApi`, a `Resource` per path segment, a proxy `Method` per route, `Deployment` (its ID carries a hash of the routes, so new routes mean a new deployment), `Stage` `Prod` and the invoke permission, one REST API per function |
| `HttpApi` event | `ApiGatewayV2` `Api`, `Integration`, `Route`, `Stage` and the invoke permission, one API per function, from the [`http_api`](http-api.md) pattern |
| `StateMachine` (`Definition`, `Policies`, `Schedule` and `EventBridgeRule` events) | `StepFunctions::StateMachine`, its `{Name}Role`, and for each event the rule and a role that may start the execution |
| `SimpleTable` | `DynamoDB::Table`, on-demand unless `ProvisionedThroughput` is given |
| `Connector`, or `Connectors` inside a function | `IAM::ManagedPolicy` `{Name}Policy` on the source function's role (`{Name}PolicyDestination{N}` for a list), for `Read` and `Write` on an SQS queue, SNS topic, S3 bucket, DynamoDB table or `SimpleTable`, or a function |
| `Globals.Function`, `IgnoreGlobals` | merged into each function (`Environment.Variables` and `Tags` are merged, other keys replaced) |

Anything else (SAM policy templates such as `LambdaInvokePolicy`, other event types and resources, a local `CodeUri` that needs packaging, properties not
listed above) raises `NotImplementedError` naming it, rather than being dropped. Resources that are not
`AWS::Serverless::*` pass through unchanged.

The logical IDs of the function, role, mappings, rules, permissions, connector policies and state machine are the
ones SAM generates, so a stack deployed with the transform can move to the expanded template without replacing
those resources. The HTTP and REST APIs are not: SAM puts every route in one `ServerlessHttpApi` or
`ServerlessRestApi` built from an OpenAPI document, and `expand` makes plain resources instead, so those are
replaced. It also leaves out SAM's `lambda:createdBy` tag.

The test suite checks this against AWS's own translator (`aws-sam-translator`, a dev dependency pinned to the same
release as the types): each resource `expand` makes, with the same logical ID, has to equal what SAM makes for it.
