# The generator

`cfn-typegen` turns AWS's CloudFormation registry schemas (about 1,900 resource
types) into Python modules, for **only the types you select**.

```sh
cfn-typegen --out cfn_types AWS::SQS::Queue 'AWS::Lambda::*'
cfn-typegen --out cfn_types --template template.json
cfn-typegen --out cfn_types --all                         # everything, ~19 MB
```

Type names are case-insensitive globs and an unmatched name is an error. The
schema zip is downloaded once into `~/.cache/cfn-typegen/`; `--schemas` points at
a local copy. A rerun replaces only files it generated earlier.

## What one resource looks like

For `AWS::SQS::Queue`, one module `sqs.py` holds:

| Name | Purpose |
|---|---|
| `QueueProps` | the properties, as a `TypedDict` |
| `Queue` | the resource dict, with `Type: Literal["AWS::SQS::Queue"]` |
| `queue(**props)` | a factory; keyword arguments are checked against `QueueProps` |
| one class per nested definition | named `{Resource}{Definition}`, for example `FunctionCode` |

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
