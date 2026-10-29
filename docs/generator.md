# The generator

`cfn-typegen` turns AWS's CloudFormation registry schemas (about 1,900 resource
types) into Python modules, for **only the types you select**.

```sh
cfn-typegen --out cfn_types AWS::SQS::Queue 'AWS::Lambda::*'
cfn-typegen --out cfn_types --template template.json
cfn-typegen --out cfn_types --all                         # everything, ~5.8 MB, ~4 MB with --no-docs
cfn-typegen --out cfn_types --no-docs AWS::SQS::Queue     # without description docstrings
```

Type names are case-insensitive globs and an unmatched name is an error. The
schema zip is downloaded once into `~/.cache/cfn-typegen/` and reused; `--schemas` points at
a local copy. A rerun replaces only files it generated earlier.

`--no-docs` leaves out the description docstrings (the first sentence of each property's
AWS documentation). The types are identical; the output is about 30% smaller.

## Refreshing

The cached schemas are never updated on their own, so a resource or property AWS added last
week will not appear. To pick it up, download the schemas again and regenerate:

```sh
cfn-typegen --refresh --out cfn_types AWS::SQS::Queue AWS::Lambda::Function
```

`--refresh` re-downloads the zip first (also available on `search`). A failed download leaves
the existing cache untouched. Each generated file records the snapshot it came from, in a
header line such as `# Schema snapshot: sha256:3f9c1a0b7d2e`, so you can tell whether two
outputs match. Regenerating with the same command replaces the files from the earlier run.

## Finding a type name

Not sure what a resource is called? Search by words in the name or description:

```sh
$ cfn-typegen search load balancer --limit 4
AWS::Lightsail::LoadBalancer
AWS::ElasticLoadBalancing::LoadBalancer
AWS::ElasticLoadBalancingV2::LoadBalancer   Specifies an Application Load Balancer, a Network Load Balancer, ...
AWS::Lightsail::LoadBalancerTlsCertificate
```

Every word must match. A hit in the resource's own name ranks above a hit elsewhere in the
type name, which ranks above a hit only in the description. Descriptions that merely
repeat the name are hidden. Copy the names you want into a generate command.

## What one resource looks like

For `AWS::SQS::Queue`, one module `sqs.py` holds:

| Name | Purpose |
|---|---|
| `QueueProps` | the properties, as a `TypedDict` |
| `Queue` | the resource dict, with `Type: Literal["AWS::SQS::Queue"]` |
| `queue(**props)` | a factory; keyword arguments are checked against `QueueProps` |
| one class per nested definition | named `{Resource}{Definition}`, for example `FunctionCode` |

The files start with `# fmt: off` and `# ruff: noqa`, so `ruff format --check` and `ruff check`
(or black) leave generated code alone and you do not need to exclude the directory.

Factories also take `depends_on`, `deletion_policy`, `update_replace_policy`,
`condition` and `metadata` as snake_case keywords, so they never collide with a
property name. Python keywords and builtins get a trailing underscore
(`lambda_`).

## Why the checker is strict

- **Closed TypedDicts.** Shapes the schema marks `additionalProperties: false` are
  emitted with `closed=True` (PEP 728). That is what turns `MemorySise` into an
  error; `ty` ignores unknown keywords on ordinary TypedDicts.
- **`Expr[T]` everywhere.** A property is `T` or an intrinsic, because
  CloudFormation accepts `Ref`, `Fn::GetAtt` and friends wherever a value goes.
- **Read-only properties are left out.** You cannot set `Arn` or `QueueUrl`, so the
  inputs do not offer them.

## Known gaps

- Enums are plain `str`, not `Literal`, so values AWS adds later never break you.
- `oneOf` constraints between properties are not modelled.
- Arrays are `list`, which is invariant: a variable typed `list[Tag]` must be
  `list[Expr[Tag]]` to be passed in. `cfn.tags()` returns the right type.
- Types do not replace `cfn-lint`: they check shape, not values.
