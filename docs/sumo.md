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

The [catalog of sumo patterns](sumo-patterns.md) lists every pattern with a link to its code and the resources it creates.

- **Patterns**: a queue with its
  dead-letter queue, a Lambda execution role, an SQS trigger, an HTTP API with a JWT authorizer, a CloudFront
  static site (with an optional domain and ACM certificate), mandatory company tags and company rules.
  The rest, in their own modules (`loadbalancer`, `storage`, `constructs`, `integrations`), are the load balancer
  pieces, encrypted storage, a VPC, Fargate services, alarms and scaling, API Gateway, messaging and data flows.
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

## Recommended: start with sumo, then eject what you use

A volatile API is a good trade while you are exploring and a poor one once a template is in production. So the
suggested path is in two steps:

1. **Start with sumo.** Install it, import the patterns and the pre-generated types, and get a stack working.
   Nothing to configure, nothing to copy. Use it to find out which patterns you actually need and which
   defaults you end up overriding.
2. **Eject the parts you used.** Once you know, copy those pieces into your own package and drop the
   dependency on `cfn-typed-sumo` (keep `cfn-typed`, whose API is the reliable one). From then on your
   patterns change when *you* decide, not when a release does.

What ejecting takes:

- **Patterns.** Copy the functions you imported from `packages/sumo/src/cfn_typed_sumo/` (for example
  `queue_with_dlq` from `patterns.py`) into a module of your own, along with any small helper they call, and
  change the imports. They are plain functions over plain dicts and depend only on `cfn-typed` and the types,
  so there is nothing else to untangle. The tests next to them are worth copying too.
- **Types.** Do not copy generated files. List the resource types you actually use in your own
  `cfn-typegen.toml` (the `AWS::SQS::Queue`-style names, or a glob per service) and let `cfn-typegen` produce them,
  as [Distributing patterns](distributing.md) describes. Then replace `from cfn_typed_sumo.types import sqs` with
  an import from your generated module. Because the sumo list is just such a config, copying the lines you need
  from `packages/sumo/cfn-typegen.toml` is a fine start, and you ship only the services you use.
- **Where it goes.** [A typical project](project-layout.md) shows a layout for this: a `cfn/` directory with
  `patterns/`, `stacks/` and the generated types.
- **Commit or generate?** Keep `cfn-typegen.toml` in the repository either way. With only a handful of types,
  committing the generated files is fine: the build needs no extra step, and the code is there to read. As the count
  grows they become a lot of generated code in every review and diff, and it is tidier to gitignore the
  directory and run `cfn-typegen` at build time, in CI and in development (a one-line `conftest.py` does it for
  tests). [Distributing patterns](distributing.md#build-setup) has the setup.
- **Check the result.** The imports are the only thing that changes, so the type checker and your
  [tests](testing.md) will tell you if something was missed. Render a template before and after: the output
  should be identical.

You do not have to eject everything at once. Ejecting a pattern as soon as you want to change it is a common
trigger, and a pattern you have not touched can keep coming from sumo until you do. Once you have, remove
`cfn-typed-sumo` from your dependencies so no import quietly slips back.

If you would rather not follow a volatile API from the start, skip step 1 and take what you need from sumo's
source straight away. The patterns are plain functions over plain dicts, so copying one costs nothing.
