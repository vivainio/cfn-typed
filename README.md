# cfn-typed

CloudFormation templates as typed Python dicts. Resource factories and their
`TypedDict`s are **generated from the official CloudFormation registry
schemas** (1,873 resource types), so a type checker catches typos, wrong types
and missing required properties before CloudFormation does. Checked with
[`ty`](https://docs.astral.sh/ty/).

```python
import json
import cfn_typed as cfn
from cfn_types import sqs  # generated, see below

template: cfn.Template = {
    "Resources": {
        "DLQ": sqs.queue(),
        "Queue": sqs.queue(
            VisibilityTimeout=180,
            RedrivePolicy={"deadLetterTargetArn": cfn.get_att("DLQ", "Arn"), "maxReceiveCount": 3},
        ),
    },
}
print(json.dumps(template, indent=2))
```

```text
error[unknown-argument]: Argument `MemorySise` does not match any known parameter of function `function`
error[invalid-argument-type]: Expected `Expr[int]`, found `Literal["30"]`
error[missing-argument]: No arguments provided for required parameters `Code`, `Role`
```

## Generating only what you use

The package ships no resource types. You generate the ones you need into your
own project, so the output stays small (four resources is about 44 KB):

```sh
cfn-typegen --out cfn_types AWS::SQS::Queue 'AWS::Lambda::*'
cfn-typegen --out cfn_types --template template.json   # types a JSON template uses
cfn-typegen --out cfn_types --all                      # everything, ~19 MB
```

Type names are case-insensitive globs and an unmatched name is an error. The
schema zip is downloaded once into `~/.cache/cfn-typegen/`; `--schemas` points at a local copy.
Rerunning replaces earlier generated files in the output directory.

## Layout of the generated modules

One module per service. For `AWS::Lambda::Function` there is
`lambda_.function(**props)` (the factory), `lambda_.Function` (the resource dict),
`lambda_.FunctionProps`, and one type per nested definition
(`lambda_.FunctionCode`, ...). Python keywords get a trailing `_`. Factories also
take `depends_on`, `deletion_policy`, `update_replace_policy`, `condition` and
`metadata` as snake_case keywords, so they never collide with a property name.

`cfn_typed` itself holds the runtime pieces the generated code imports:
`intrinsics` (`Ref`, `GetAtt`, ..., and `Expr[T]` = `T | Intrinsic`, which every
generated property uses), `base` (`Template`, `Tag`, `build`) and a few helpers.
`examples/` has a worked SQS + Lambda stack and `examples/cfn_types/` is its
generated output.

## Patterns

Helper functions that return a resource or a small fragment (a queue with its
dead-letter queue, a Lambda role, ...) are documented in the book, with working
code in `examples/patterns.py`. Build it locally with `uv run zensical serve`.

## Type checking notes

Read-only properties (`Arn`, `Id`, ...) are left out of the inputs. Shapes whose
schema says `additionalProperties: false` are emitted as PEP 728 `closed=True`
TypedDicts, which is what makes `ty` reject unknown names.

Known gaps: enums are plain `str` (no `Literal`, so newly added values never
break you); `oneOf` constraints between properties are not modelled; arrays are
`list`, which is invariant, so a variable typed `list[Tag]` needs
`list[Expr[Tag]]`.

## Development

The repo contains no generated types. The examples and tests need a few, which are
generated into `examples/cfn_types/` (gitignored) the first time pytest runs, or by hand:

```sh
cfn-typegen --out examples/cfn_types AWS::SQS::Queue AWS::Lambda::Function \
    AWS::Lambda::EventSourceMapping AWS::IAM::Role
uv run ty check
uv run pytest
uv run zensical serve        # the book
```
