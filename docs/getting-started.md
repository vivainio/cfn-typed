# Getting started

## Install

```sh
uv add cfn-typed          # the runtime pieces and the cfn-typegen command
uv add --dev ty           # the type checker this project is tested with
```

Until it is on PyPI, install from GitHub:
`uv add git+https://github.com/vivainio/cfn-typed`. Python 3.14 or later is required.

## Generate the types you use

The package ships no resource types. You generate the ones your templates need
into your own project:

```sh
cfn-typegen --out cfn_types AWS::SQS::Queue 'AWS::Lambda::*' AWS::IAM::Role
```

Or point it at a template that already exists and it emits exactly the types that
template uses:

```sh
cfn-typegen --out cfn_types --template template.json
```

Each service becomes one module (`cfn_types/sqs.py`, `cfn_types/lambda_.py`, ...).
Each run writes a clean set of modules and replaces only files it generated earlier.
Whether to commit them or generate them in CI is up to you.

## A minimal program

The whole program is one file: build the template as data, print it as JSON.

```python
--8<-- "examples/minimal.py:main"
```

`build` is a pure function of its arguments, so tests can call it directly. `main`
only reads the stage from the command line and prints. Render and deploy:

```sh
python minimal.py prod > template.json
aws cloudformation deploy --template-file template.json --stack-name jobs-prod
```

## Let the checker help

```sh
ty check
```

Anywhere a property takes a value you can pass either a literal or an intrinsic
such as `cfn.ref(...)` or `cfn.get_att(...)`: every generated property is
`Expr[T]`, meaning `T` or an intrinsic. Unknown names, wrong types and missing
required properties are reported before any template exists. Keep `cfn-lint` in CI
as well: types do not check values, such as whether a Lambda runtime exists.
