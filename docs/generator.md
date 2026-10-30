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

## Configuration file

With no arguments, `cfn-typegen` reads `cfn-typegen.toml` in the current directory; point at
another file with `--config path.toml`. Relative paths inside it are relative to the file.

```toml
out = "src/acme_cfn"
types = ["AWS::S3::*", "AWS::Lambda::*"]   # or: all = true
templates = ["template.json"]              # optional: also the types these use
docs = false
schemas = "CloudformationSchema.zip"       # optional: a pinned snapshot
optional = ["AWS::Foo::Bar.Baz"]           # optional: required in the schema, but may be omitted
required = ["AWS::Foo::Bar.Qux"]           # optional: not required in the schema, but must be given
unconstrained = ["AWS::Foo::Bar.Quux"]     # optional: drop this property's value constraints
constraints = true                         # false: leave out the CONSTRAINTS tables
literal_enums = false                      # true: fixed sets of values become Literal[...]
```

`optional` and `required` correct the registry where it disagrees with CloudFormation: each
`Type.Property` becomes `NotRequired` or required. Three corrections are built in, taken from
cfn-lint: `AWS::CloudFormation::Stack.StackName` may be omitted (CloudFormation names a nested
stack) and `TemplateURL` is required, and `AWS::Batch::QuotaShare.QuotaShareName` is required.
Your entries add to those. Checked against cfn-lint's bundled
schemas, these are the only differences in `required` across about 1,800 resource types.

Types named on the command line replace the file's `types`; `--out` overrides `out`.

## Constraints and `Literal` enums

Each module ends with a `CONSTRAINTS` table: the registry's allowed values, patterns, lengths,
ranges and item counts, for [`assert_constraints_hold`](testing.md#checking-values-against-the-schema).
It is written as small as it goes (one-letter keys, no spaces, shared parts written once), so it
adds about 30% to the output: 5.3 MB for every type, against 4.0 MB without. `--no-constraints`
(or `constraints = false`) leaves it out, and `unconstrained = ["Type.Property"]` drops one
property whose constraint is wrong. Patterns Python's `re` cannot compile are left out.

`--literal-enums` (or `literal_enums = true`) goes further and types each property that has a
fixed set of values as `Literal[...]`, so the editor completes the values and a wrong one is a
type error:

```python
logs.log_group(RetentionInDays=30)   # ok
logs.log_group(RetentionInDays=31)   # error: Expected Literal[1, 3, 5, 7, 14, ...]
```

It is off by default because AWS adds values faster than the schema zip changes: a valid new
value is a type error until you regenerate with `--refresh`. The constraints check has no such
cost, because it only runs when you ask for it.

## Publishing generated types

`cfn-typegen init-repo` scaffolds a repository that holds *only* generated types, ready to
publish under your own name:

```sh
cfn-typegen init-repo acme-cfn 'AWS::S3::*' 'AWS::Lambda::*'
cd acme-cfn && uv run cfn-typegen
```

It writes `cfn-typegen.toml` (the output directory and the types to generate), a `pyproject.toml`, a weekly workflow that
regenerates against fresh schemas and opens a pull request, and a workflow that builds and
publishes on a `v*` tag. Name no types to generate every one. Keep hand-written helpers in
a separate package, so regenerating can never overwrite them.

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
