# cfn-typed-sumo: the fat pattern library

`cfn-typed` is the small, careful half: the generator, the template types, intrinsics, rendering and
the permission names. Its API is meant to stay **reliable**, and changes to it are made with that in mind.

`cfn-typed-sumo` is the other half: a **fat pattern library** built from the same repository, on top of
`cfn-typed`. It brings the generated types and a growing set of ready-made patterns, so you can
start from working building blocks instead of copying code out of the book. Because the types for the
core services come pre-generated, it is also the quickest way to **try things out**: install it and start
writing templates, with no `cfn-typegen` step and no config.

```sh
uv add cfn-typed-sumo        # brings cfn-typed with it; nothing to generate first
```

```python
from cfn_typed_sumo import queue_with_dlq, lambda_role
from cfn_typed_sumo.types import lambda_, sqs
```

## What is in it

- **Patterns** (`cfn_typed_sumo.patterns`, re-exported from `cfn_typed_sumo`): a queue with its
  dead-letter queue, a Lambda execution role, an SQS trigger, an HTTP API with a JWT authorizer, a CloudFront
  static site (with an optional domain and ACM certificate), mandatory company tags and company rules.
  The other patterns in this book are still in `examples/` and move in over time.
- **Generated types** (`cfn_typed_sumo.types`): the resource types the patterns use plus the core
  services (IAM, Lambda, SQS, SNS, S3, KMS, DynamoDB, Logs, Events, SSM, CloudWatch) and the usual
  compute, web and data ones (EC2, ECS, ECR, EKS, ELBv2, API Gateway, CloudFront, Route 53, RDS, Step Functions, Kinesis, Secrets Manager, Cognito and more), shipped in the wheel. They are public: use them for your own resources too. The list is
  `packages/sumo/cfn-typegen.toml`; anything else you still generate yourself with `cfn-typegen`.

## The deal

| | `cfn-typed` | `cfn-typed-sumo` |
|---|---|---|
| What it is | the mechanics and the facts | patterns and opinions |
| API | **kept reliable** | **volatile**: names, signatures and defaults change between releases |
| Size | small | fat, and it grows |
| Use it when | you want a stable base to build your own helpers on | you want working patterns now and can follow its changes |

Patterns are judgements about what is sensible, so they will be adjusted as better judgements come
along, and the generated types can be renamed or regenerated when the generator improves. Pin the exact
version (`cfn-typed-sumo==X.Y.Z`; the two packages are released in lockstep, so it pins `cfn-typed` for you) and
read the release notes before you move.

If you would rather not follow a volatile API, take what you need from sumo's source and keep it in your own
package, as [Distributing patterns](distributing.md) describes. The patterns are plain functions over plain
dicts, so copying one costs nothing.
