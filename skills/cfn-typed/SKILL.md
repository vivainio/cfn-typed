---
name: cfn-typed
description: Write, check and render AWS CloudFormation as typed Python with cfn-typed and its construct library cfn-typed-sumo. Use when a project has or needs CloudFormation templates, when the user wants infrastructure as typed code without CDK, or when they mention cfn-typed, cfn-typed-sumo or cfn-typegen.
---

# cfn-typed

CloudFormation templates as plain Python dicts. Resource factories and their `TypedDict`s are generated from the
official CloudFormation registry schemas, so a type checker (`ty`, mypy, pyright) catches misspelled properties, wrong
types and missing required properties before CloudFormation does. The output is ordinary template JSON/YAML: no synth
step, no hashed logical IDs, Python 3.14+.

Two packages:

- **`cfn-typed`**: the stable core. Generated types, intrinsics, rendering, permission names, the `cfn-typed` command.
- **`cfn-typed-sumo`**: constructs (ready-made building blocks) and pre-generated types for the common services.
  Opinionated and volatile: names, signatures and defaults change between releases, so pin the version.

```sh
uv add cfn-typed-sumo        # brings cfn-typed; no cfn-typegen step for the common services
uv add --dev ty
```

## Core constructs: start here

A construct is an ordinary function returning one resource, a `Resources` dict, or a **handle** (a small dataclass with
a `resources` field and the logical IDs and references you need, such as `orders.queue_arn`). Logical IDs come from the
`name` argument and are documented, never generated behind your back. Combine pieces with `cfn.combine(...)`, which takes
dicts and handles and refuses to silently overwrite a logical ID.

| Construct (`cfn_typed_sumo...`) | Creates | Handle / notes |
|---|---|---|
| `constructs.function(name, code=, handler=, runtime=, memory=, timeout=, environment=, statements=)` | Lambda `{name}`, role `{name}Role`, log group `{name}Logs` | `.function`, `.role`, `.log_group`; `statements` become the role's policy |
| `queue_with_dlq(name, visibility_timeout=, max_receive_count=)` | `{name}Queue`, `{name}DLQ` | `.queue_arn`, `.queue_url`, `.dlq_url` |
| `sqs_event_source(function_logical, queue_arn)` | Lambda event source mapping from a queue | one resource |
| `constructs.schedule(name, "cron(...)", function_logical)` | EventBridge rule and invoke permission | `{name}Rule`, `{name}Permission` |
| `constructs.invoke_permission(function_logical, principal, source_arn)` | Lambda permission for a service | one resource |
| `storage.dynamodb_table("pk", "sk", gsis=)` | on-demand table, point-in-time recovery, deletion protection on | one resource; keys are `"name"` or `("name", "N")` |
| `storage.encryption_key(name, alias=)` | KMS key with rotation and alias | `{name}Key`, `{name}KeyAlias` |
| `storage.secure_bucket(name, key_arn=)` | private encrypted bucket and policy | `{name}Bucket`, `{name}BucketPolicy` |
| `http_api(name, function=, routes=["GET /orders"], jwt=)` | HTTP API to a Lambda, optional JWT authorizer | `.api_id`, `.endpoint` |
| `integrations.api_to_lambda(name, function_logical)` | REST API proxying to a Lambda | `Resources` |
| `integrations.event_to_lambda(name, function_logical, pattern= or schedule=)` | EventBridge rule to a Lambda | `Resources` |
| `integrations.stream_trigger(name, function_logical, table_logical)` | DynamoDB stream to a Lambda | handle |
| `integrations.bucket_to_lambda(name, function_logical, bucket_name=)` | bucket that invokes a Lambda | `Resources` |
| `integrations.fan_out(name, subscribers)` | one topic, a queue plus DLQ per subscriber | `Resources` |
| `constructs.lambda_errors_alarm(function_logical)`, `queue_backlog_alarm(queue, threshold=)`, `alarm_topic(name, emails)` | CloudWatch alarms and notification topic | |
| `constructs.vpc`, `fargate_service`, `loadbalancer.*`, `static_site` | networking, containers, web | see the book's pattern catalog |

[resources/example-service.py](resources/example-service.py) assembles a queue, a function, an SQS trigger, a schedule, a
table and an alarm. Copy it as a starting point.

If no construct fits, use the generated factory directly, or copy a construct and change it (they are short):

```python
import cfn_typed as cfn
from cfn_typed_sumo.types import sqs        # generated types, public; others via cfn-typegen

"Queue": sqs.queue(VisibilityTimeout=180, RedrivePolicy={"deadLetterTargetArn": cfn.get_att("DLQ", "Arn"), "maxReceiveCount": 3})
```

- A factory is `service.snake_case_resource(**Properties)`; properties keep CloudFormation's PascalCase names, and
  nested objects are plain dict literals that the checker validates.
- Resource attributes are snake_case keywords: `depends_on`, `deletion_policy`, `update_replace_policy`, `condition`,
  `metadata`.
- Intrinsics are builders that return the plain dict: `cfn.ref`, `cfn.get_att`, `cfn.sub`, `cfn.join`, `cfn.select`,
  `cfn.split`, `cfn.find_in_map`, `cfn.if_`, `cfn.get_azs`, `cfn.base64`, `cfn.cidr`, `cfn.import_value`; conditions
  `cfn.equals`, `cfn.and_`, `cfn.or_`, `cfn.not_`, `cfn.condition_ref`. Pseudo parameters: `cfn.ref("AWS::Region")`.
- `cfn.Params()` declares template parameters once (plain or SSM-backed) and returns the `Ref`; put
  `params.declarations()` under `"Parameters"`.
- IAM: `from cfn_typed.permissions import Sqs` gives `Sqs.ReceiveMessage` (a typo is an attribute error);
  `cfn.allow(...)`/`cfn.deny(...)` build statements; `cfn_typed.grants` has the CDK's permission sets, e.g.
  `grants.Sqs.Queue.consume_messages.on(queue_arn)`. Grants are an opinion layer: pin the version.
- Render: `cfn.to_json(template)`, `cfn.to_yaml(template)` (needs `cfn-typed[yaml]`).

## The command line

Types for a service the sumo package does not ship, or for a package without sumo:

```sh
cfn-typegen --out cfn_types AWS::SQS::Queue 'AWS::Lambda::*'     # only what you use; rerun to regenerate
cfn-typegen --out cfn_types --template template.json             # the types an existing template uses
cfn-typegen search load balancer                                 # find a type name
```

One module per service (`cfn_types/sqs.py`, `cfn_types/lambda_.py`; keywords get a trailing `_`). Never hand-edit them.

`cfn-typed` works on template files (JSON, or YAML with `cfn-typed[yaml]`), so it also checks templates it did not write:

```sh
ty check                                          # types: the main safety net
cfn-typed check template.yaml                     # references, unused parameters, quotas, IAM names, Lambda runtimes
cfn-typed check template.yaml --schemas cfn_types # plus registry schema constraints (needs generated types)
cfn-typed ls template.yaml -t lambda              # resources: logical id, type, name
cfn-typed emit template.yaml -f json              # convert JSON and YAML either way
cfn-typed diff rendered/ template.yaml            # compare with the committed rendered/template.yaml
cfn-typed import template.json -o stack.py        # existing template -> typed Python (see below)
cfn-typed skill                                   # print this skill, and where its directory is
```

To give your own program the same subcommands (`emit`, `check`, `diff`, `ls`) for the stacks it builds, call
`cfn_typed.cli.main({"orders-prod": build_prod}, schemas=cfn_types)` from its `main()`.

**Test by rendering.** Commit the rendered YAML and have CI assert the code still renders exactly that:
`cfn_typed.testing.assert_matches_file(template, "rendered/stack.yaml")`; rerun with `CFN_TYPED_UPDATE=1` to accept an
intended change.

**Deploy** with the AWS CLI; cfn-typed only produces the template (it does not package or upload code):
`aws cloudformation deploy --template-file template.json --stack-name NAME`. To review first, use a change set:
[resources/change-set.md](resources/change-set.md).

## Taking over an existing template

`cfn-typed import template.json -o stack.py` writes a `build() -> cfn.Template` that renders back to the same template:
factory calls for resources, `cfn.*` builders for intrinsics, logical IDs and values untouched. What a factory cannot
express (`Custom::*`, `CreationPolicy`, `UpdatePolicy`, property names that are not identifiers) stays a plain dict with a
comment; the file header lists them. Generate the types first with `cfn-typegen --template`. Prove the result with
`assert build() == json.load(open("template.json"))`, run `ty check`, and review a change set before any deploy.

## Rules

- **Never change the logical ID of a stateful resource** (table, bucket, queue, database, stream): a new ID is a
  replacement, which deletes the old resource. Set `deletion_policy="Retain"` first; use a resource import to move.
- Do not invent property or type names: `cfn-typegen search`, or read the generated module.
- Do not execute a change set the user has not seen.
- Constructs are opinions: when a default does not suit the user (retention, encryption, tags), pass the argument or
  copy and change the construct, rather than working around it after rendering.
