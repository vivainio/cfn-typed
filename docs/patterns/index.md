# Patterns

!!! note "Patterns are opinions"
    Everything in this section is a judgement about what is sensible, not a fact about CloudFormation, so it is
    kept apart from the generated types and the permission names. Treat the patterns as examples to copy and change,
    not as an API. See [Facts first, opinions fenced](../index.md#facts-first-opinions-fenced).

A **pattern** is an ordinary function that returns a resource, or a small
*fragment* of several resources. That is the whole idea. There is no base class,
no registry and no construct tree.

```python
def queue_with_dlq(name: str, *, visibility_timeout: int = 30) -> Resources: ...
```

A fragment is a `Resources` dict, a plain `dict[str, AnyResource]`, so you combine
fragments with `|` and drop the result into `Template["Resources"]`.

A pattern can also return a **handle**: a small dataclass with a `resources` field plus
the logical IDs and references callers need (`orders.queue_arn`). `cfn.combine` accepts
a dict or any handle, via the `HasResources` protocol.

## Conventions the patterns follow

- **Logical IDs are derived from a `name` argument** and documented:
  `queue_with_dlq("Order")` creates `OrderQueue` and `OrderDLQ`. Callers then use
  the handle (`orders.queue_arn`) rather than retyping the IDs. The names are visible
  in the call, never generated behind your back.
- **A pattern that creates one resource returns that resource's type**
  (`iam.Role`), and a pattern that creates several returns `Resources`, or a handle with a
  `resources` field when callers need to refer back to what it made.
- **Inputs are typed with `Expr[T]`**, so a caller can pass a literal or a
  `Ref`/`GetAtt`.
- **Optional pieces are only emitted when given.** No `Tags: []` noise in the output.

## Where the code lives

The patterns in this book that live in a package ship as **`cfn-typed-sumo`**, a second
package built from this repository that depends on `cfn-typed`. It is a fat pattern library with a
volatile API, unlike the core ([details](../sumo.md)):

```sh
uv add cfn-typed-sumo
```

The code is in
[`packages/sumo/src/cfn_typed_sumo/patterns.py`](https://github.com/vivainio/cfn-typed/blob/main/packages/sumo/src/cfn_typed_sumo/patterns.py),
type-checked and tested like any other code, and every snippet on these pages is pulled
straight from that file. Import them (`from cfn_typed_sumo import queue_with_dlq`) or copy
what you need and change it.

The package also ships the generated types its patterns use as a public module,
`cfn_typed_sumo.types`. They are generated from `packages/sumo/cfn-typegen.toml`, which lists
the resource types the patterns need plus the core and everyday services (IAM, Lambda, SQS, SNS, S3,
KMS, DynamoDB, EC2, ECS, both API Gateways, CloudFront, RDS and so on, but not all of AWS); the repository does not contain them, and CI and the
release build generate them. The snippets start from these imports:

```python
--8<-- "packages/sumo/src/cfn_typed_sumo/patterns.py:imports"
```

Every pattern on these pages is in the package: the [catalog](../sumo-patterns.md) lists them with
links to the code and the resources each one creates. Only the stacks that assemble them stay in `examples/`.

| Pattern | Creates |
|---|---|
| [Lambda execution role](lambda-role.md) | one `AWS::IAM::Role` |
| [Queue with a dead-letter queue](queue-with-dlq.md) | `{name}Queue` and `{name}DLQ` |
| [SQS-triggered Lambda](sqs-trigger.md) | one `AWS::Lambda::EventSourceMapping` |
| [Load balancer building blocks](load-balancer.md) | a load balancer, target group, listener or ingress rule |
| [HTTP API with a JWT authorizer](http-api.md) | an HTTP API, a Lambda integration, a JWT authorizer, one route per route key and the invoke permission |
| [One load balancer, several ports](web-entrypoint.md) | security group, load balancer, and a target group and listener per port |
| [Encrypted storage](storage.md) | a KMS key, a private bucket and its policy, a table, a repository |
| [Publishing values through SSM](publishing.md) | SSM parameters that one stack publishes and another reads |
| [Parameters as variables](parameters.md) | template parameters (including SSM), declared once and used as variables |
| [CDK L2 constructs as patterns](cdk-l2.md) | a Lambda function, a schedule, an SNS subscription, a VPC, a Fargate service, alarms, and auto scaling for services, Lambda aliases and tables |
| [Web frontends](web-frontends.md) | a CloudFront static site, a REST API in front of a Lambda or a table, a Lambda behind a load balancer, DNS aliases |
| [Messaging and events](messaging.md) | an SNS fan-out to queues with dead-letter queues, EventBridge rules to a Lambda or a queue |
| [Data flows](data-flows.md) | a table stream into a Lambda, a bucket that invokes a Lambda, Firehose into a bucket |
| [Fargate tasks](containers.md) | a cluster, a task and its two roles, for workers and for tasks a Lambda starts |
| [Serverless Framework in a few lines](serverless.md) | the Serverless `functions:` example, a scheduled Lambda, as patterns |
| [Mandatory tags](mandatory-tags.md) | nothing, but resolves and checks the tags a company requires, from service and per-resource values |
| [Company rules](company-rules.md) | nothing, but checks the finished template against rules of your own, as one more layer on the built-in checks |
| [Composing fragments](composing.md) | nothing, but how to combine the above safely |
| [A complete stack](complete-stack.md) | all of the above in one template |
