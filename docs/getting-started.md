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

## Your first template

```python
import json

import cfn_typed as cfn
from cfn_types import sqs

template: cfn.Template = {
    "AWSTemplateFormatVersion": "2010-09-09",
    "Resources": {
        "Jobs": sqs.queue(VisibilityTimeout=60, Tags=cfn.tags(Service="jobs")),
    },
    "Outputs": {"JobsUrl": {"Value": cfn.ref("Jobs")}},
}
print(json.dumps(template, indent=2))
```

```sh
python template.py > template.json
aws cloudformation deploy --template-file template.json --stack-name jobs
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
