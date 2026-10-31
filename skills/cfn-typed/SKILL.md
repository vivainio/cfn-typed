---
name: cfn-typed
description: Write, check and migrate AWS CloudFormation as typed Python with cfn-typed. Use when a project has or needs CloudFormation templates, when moving a Serverless Framework (serverless.yml) or other existing stack to code, or when the user mentions cfn-typed, cfn-typegen or typed CloudFormation.
---

# cfn-typed

CloudFormation templates as plain Python dicts, with resource factories and `TypedDict`s generated from the official
CloudFormation registry schemas. A type checker (`ty`, mypy, pyright) catches misspelled properties, wrong types and
missing required properties before CloudFormation does. The output is ordinary template JSON/YAML: no synth step, no
hashed logical IDs, no runtime beyond Python 3.14+.

Run `cfn-typed --help` and `cfn-typegen --help` for the exact options; they are the source of truth.

## Setup

```sh
uv add cfn-typed            # add 'cfn-typed[yaml]' for YAML output and YAML input
uv add --dev ty
cfn-typegen --out cfn_types AWS::SQS::Queue 'AWS::Lambda::*'     # generate only the types you use
cfn-typegen --out cfn_types --template template.json             # ...or the types an existing template uses
cfn-typegen search load balancer                                 # find a type name
```

The package ships no resource types: generate them into the project. One module per service (`cfn_types/sqs.py`,
`cfn_types/lambda_.py`; Python keywords get a trailing `_`). Rerunning replaces earlier generated files.

## Writing a template

```python
import cfn_typed as cfn
from cfn_types import sqs

def build() -> cfn.Template:
    return {
        "Resources": {
            "DLQ": sqs.queue(),
            "Queue": sqs.queue(
                VisibilityTimeout=180,
                RedrivePolicy={"deadLetterTargetArn": cfn.get_att("DLQ", "Arn"), "maxReceiveCount": 3},
            ),
        },
    }
```

- A factory is `service.snake_case_resource(**Properties)`; properties keep CloudFormation's PascalCase names.
- Resource attributes are snake_case keywords: `depends_on`, `deletion_policy`, `update_replace_policy`, `condition`,
  `metadata`. They cannot collide with a property name.
- Nested objects are plain dict literals; the checker validates them against the generated `TypedDict`s.
- Intrinsics are builders returning the plain dict CloudFormation expects: `cfn.ref`, `cfn.get_att`, `cfn.sub`,
  `cfn.join`, `cfn.select`, `cfn.split`, `cfn.find_in_map`, `cfn.if_`, `cfn.get_azs`, `cfn.base64`, `cfn.cidr`,
  `cfn.import_value`; conditions use `cfn.equals`, `cfn.and_`, `cfn.or_`, `cfn.not_`, `cfn.condition_ref`.
  Pseudo parameters are `cfn.ref("AWS::Region")`.
- `cfn.Params` declares template parameters once (plain or SSM-backed) and returns the `Ref`.
- Render with `cfn.to_json(template)` or `cfn.to_yaml(template)`.
- IAM action names: `from cfn_typed.permissions import Sqs` then `Sqs.ReceiveMessage` (a typo is an attribute error).
  `cfn_typed.policy` builds statements (`allow`, `deny`); `cfn_typed.grants` is the CDK's permission sets (an opinion
  layer that may change between releases: pin the version if you use it).

## Checking

```sh
ty check                                  # types: the main safety net
cfn-typed check template.yaml             # references, unused parameters, quotas, IAM names, Lambda runtimes
cfn-typed check template.yaml --schemas cfn_types      # plus the registry schema constraints
cfn-typed ls template.yaml -t lambda      # resources: logical id, type, name
cfn-typed emit template.yaml -f json      # convert between JSON and YAML
cfn-typed diff rendered/ template.yaml    # compare with the committed rendered/template.yaml
```

Commit the rendered YAML and have CI assert the code still renders exactly that:
`cfn_typed.testing.assert_matches_file(template, "rendered/stack.yaml")`; `CFN_TYPED_UPDATE=1` accepts an intended change.
To give your own program these subcommands, call `cfn_typed.cli.main(stacks, schemas=cfn_types)` from your `main()`.

## Migrating an existing stack (Serverless Framework, CDK, SAM, hand-written)

The aim is a change set that shows **no changes**. Import the CloudFormation that exists today, not the source config.

1. Capture the template: `sls package` and take `.serverless/cloudformation-template-update-stack.json`, or
   `aws cloudformation get-template --stack-name NAME --query TemplateBody`.
2. `cfn-typegen --out cfn_types --template captured.json`  (`Custom::*` resources are skipped: they have no schema).
3. `cfn-typed import captured.json -o stack.py` writes a `build() -> cfn.Template`: resources become factory calls,
   intrinsics become `cfn.*` builders, logical IDs and values are kept, so it renders back to the same template.
   Anything a factory cannot express (`Custom::*`, `CreationPolicy`, `UpdatePolicy`, property names that are not
   identifiers) stays a plain dict with a comment saying why; the file header lists them.
4. Prove equality: `cfn-typed emit stack.py`-style rendering via your `main()`, or in a test
   `assert build() == json.load(open("captured.json"))`. Run `ty check`.
5. Create a change set **without executing it** and read it before executing:
   `aws cloudformation deploy --no-execute-changeset ...` then `aws cloudformation describe-change-set ...`.
6. Only then refactor (extract helpers, parameters, shared defaults), re-checking the diff after each step.

Rules that prevent outages:
- **Never change a logical ID on a stateful resource** (DynamoDB table, S3 bucket, SQS queue, RDS, Kinesis). A new ID is
  a replacement, which deletes the old resource. Set `deletion_policy="Retain"` first, and use `import` for moves.
- Stateless resources (functions, log groups, permissions) may be replaced if the ID changes; still read the change set.
- The Serverless Framework also does packaging and upload (zip, deployment bucket, a new Lambda version per deploy).
  cfn-typed does not: `Code` points at an object you uploaded (`aws s3 cp` or CI), and you deploy with
  `aws cloudformation deploy`. Say so to the user when a project relies on `sls deploy` doing that for it.
- The importer keeps the framework's generated names (`WorkerLambdaFunction`, `ServerlessDeploymentBucket`). That is
  deliberate: renaming them is a separate, reviewed change.

## Do not

- Do not hand-edit generated files in `cfn_types/`; regenerate them.
- Do not invent property or type names: run `cfn-typegen search`, or read the generated module.
- Do not execute a change set the user has not seen.
