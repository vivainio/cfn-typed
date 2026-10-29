# cfn-typed

CloudFormation templates as typed Python dicts. Resource factories and their
`TypedDict`s are **generated from the official CloudFormation registry
schemas** (1,873 resource types), so a type checker catches typos, wrong types
and missing required properties before CloudFormation does. Checked with
[`ty`](https://docs.astral.sh/ty/).

**[Read the book](https://vivainio.github.io/cfn-typed/)** for a getting-started guide, a gallery of
pattern helpers (a Lambda role, a queue with its dead-letter queue, ...) and a
reference page per resource. Install from [PyPI](https://pypi.org/project/cfn-typed/):
`uv add cfn-typed` (or `uv add 'cfn-typed[yaml]'` for YAML output).

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
cfn-typegen --out cfn_types --all                      # everything, ~5.8 MB, ~4 MB with --no-docs
cfn-typegen --out cfn_types --no-docs AWS::SQS::Queue  # leave out the description docstrings
cfn-typegen search load balancer                       # find a type name
```

Type names are case-insensitive globs and an unmatched name is an error. The
schema zip is downloaded once into `~/.cache/cfn-typegen/`; `--schemas` points at a local copy,
and `--refresh` downloads it again to pick up new AWS resources. Then rerun your generate command.
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

## Parameters as variables

`cfn.Params` declares template parameters (plain or SSM-backed) once and returns the `Ref` to use,
so a shared "defaults" package can expose a VPC id or subnet list as variables. See the book.

## JSON or YAML

`cfn.to_json(template)` and `cfn.to_yaml(template)` (YAML needs `cfn-typed[yaml]`) render
the same template. The YAML uses short-form intrinsics (`!Ref`, `!GetAtt A.Arn`, ...).

## Testing

Commit the rendered YAML and let CI check that the code still renders exactly that:
`cfn_typed.testing.assert_matches_file(template, "rendered/stack.yaml")`. Rerun with
`CFN_TYPED_UPDATE=1` to accept an intended change. See the book. This repo does it for its own
examples (`examples/rendered/`).

## Permission names

`cfn_typed.permissions` gives IAM actions names, so `Sqs.ReceiveMessage` replaces the string
`"sqs:ReceiveMessage"` and a typo is an attribute error. The names are copied from the
[AWS CDK](https://github.com/aws/aws-cdk) (Apache-2.0, credited in `NOTICE`), for the major services,
by `scripts/sync-cdk-permissions.py` at a pinned commit. See the book.

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
scripts/build-docs.sh        # generate types and reference pages, build the book (needs zensical)
```

## Releasing

Releases are published to PyPI from GitHub with trusted publishing (no token). The
version in `pyproject.toml` stays `0.0.0.dev0`; the workflow sets it from the tag.

```sh
gh release create v0.1.0 --generate-notes
```

That runs the tests, builds with `uv build` and publishes. One-time setup on PyPI:
add a trusted publisher for the project `cfn-typed` (owner `vivainio`, repository
`cfn-typed`, workflow `publish.yml`, environment `pypi`), and create the `pypi`
environment under the repository's Settings, Environments.
