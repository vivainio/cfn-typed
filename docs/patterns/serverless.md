# Serverless Framework in a few lines

A Serverless Framework `functions:` entry is short because the framework writes the rest. This is the usual
example, a Python function that runs on a schedule:

```yaml
functions:
  worker:
    handler: handler.cleanup
    runtime: python3.12
    memorySize: 512
    timeout: 600
    events:
      - schedule: cron(0 3 * * ? *)
```

The framework expands it into a CloudFormation template of about 120 lines. You never see that template unless you
run `sls package`. The same function as [patterns](cdk-l2.md), from
[`examples/serverless.py`](https://github.com/vivainio/cfn-typed/blob/main/examples/serverless.py):

```python
--8<-- "examples/serverless.py:stack"
```

It renders to the template below, committed as
[`serverless.yaml`](https://github.com/vivainio/cfn-typed/blob/main/examples/rendered/serverless.yaml) and
checked by the test suite:

```yaml
--8<-- "examples/rendered/serverless.yaml"
```

## What is the same, and what is not

The call is longer than the YAML, and the output is shorter than the framework's. Both differences are about where
the work is done.

| | Serverless Framework | Patterns |
|---|---|---|
| Function, role, log group | generated | `function` creates `WorkerRole`, `WorkerLogs` and `Worker` |
| Schedule and invoke permission | generated | `schedule` creates `WorkerRule` and `WorkerPermission` |
| Log group retention | none by default | 30 days, an argument |
| Code packaging and upload | built in | **not done**: `Code` points at an object you uploaded |
| Deployment bucket and its policy | generated | **not done** |
| A new Lambda version per deploy | generated | **not done**; see `live_alias` in [CDK L2 constructs](cdk-l2.md#provisioned-concurrency-for-a-lambda) |
| Where you see the output | `sls package` | in the call, in the committed YAML |
| A misspelled `MemorySize` | caught when you deploy | caught by `ty` before you run anything |

The patterns produce 47 lines because they leave out the packaging half of the framework. If you only want the
CloudFormation side, that is the part you need: upload the zip with `aws s3 cp` or your CI, and pass the key. If
you want the framework to package and upload for you, a pattern is not a replacement.

The IAM role is also narrower. The framework's role gets the permissions you list under `iamRoleStatements`, and
here they are the `statements` argument of `function`, taking the same statements as [grants](../grants.md):

```python
function("Worker", ..., statements=grants.Sqs.Queue.consume_messages.on(orders.queue_arn))
```

## Moving an existing service

Capture what the framework generates and compare it with what the code renders:

1. `sls package`, then take `.serverless/cloudformation-template-update-stack.json`.
2. Build the same resources with the patterns and render them.
3. Create a change set without executing it: `aws cloudformation deploy --no-execute-changeset`, then
   `aws cloudformation describe-change-set`.

A resource whose logical ID changes is a replacement, so the names matter. The framework derives them
(`WorkerLambdaFunction`, `WorkerLogGroup`), while a pattern derives them from `name`. Name the pattern calls so
the IDs match, or accept the replacement for stateless resources.
