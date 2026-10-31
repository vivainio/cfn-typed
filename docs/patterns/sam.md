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

## What the event builders do

An event is a small typed dict. The builders exist because of two things the checker cannot do for an inline dict:

| Builder | Event | What SAM creates |
|---|---|---|
| `sqs_event(queue_arn, batch_size=10)` | `SQS` | the event source mapping and read access to the queue |
| `http_api_event(path, method)` | `HttpApi` | a route on the implicit HTTP API (or `api_id`'s) |
| `schedule_event(expression)` | `Schedule` | the rule and the permission to invoke the function |

For any other event type, build it as a typed value first (`e: serverless.FunctionS3Event = {...}`) and pass that in
`Events`.

## SAM or the patterns

SAM does the packaging side that [patterns](serverless.md) leave out (`sam build`, `sam package` upload the code and
fill in `CodeUri`), and it expands to resources you do not see until deploy. Use SAM types when you want that
workflow with checked properties. Use the plain `function` pattern when you want the exact resources in the
template, as for the [Serverless Framework](serverless.md#moving-an-existing-service) migration, with logical IDs you choose.
