# cfn-typed: agent quickstart

You are writing AWS CloudFormation as typed Python with `cfn-typed` (and optionally `cfn-typed-sumo`). Follow this
page literally. It lists the patterns to adopt, in order, with the rules that keep a template correct. Where a
step says "read", the linked book page has the detail; you do not need it to start.

Book: https://vivainio.github.io/cfn-typed/ · Source: https://github.com/vivainio/cfn-typed

## 0. What this is

- A template is a plain Python dict (`cfn.Template`). A resource is made by a generated factory,
  `service.snake_case_resource(**Properties)`. Output is ordinary CloudFormation JSON/YAML: no synth step, no
  hashed logical IDs. Python 3.14+.
- A type checker (`ty`) reports misspelled properties, wrong types and missing required properties. **Run it after
  every edit and fix what it says; do not silence it.**
- `cfn-typed` is the stable core. `cfn-typed-sumo` is a volatile pattern library on top of it: pin its version.

## 1. Set up

Pick one:

```sh
# A. Fastest: pre-generated types for common services, ready-made patterns.
uv add cfn-typed-sumo==<pinned version> && uv add --dev ty pytest

# B. Core only: generate just the types you use.
uv add cfn-typed && uv add --dev ty pytest
cfn-typegen --out cfn_types AWS::SQS::Queue 'AWS::Lambda::*' AWS::IAM::Role
cfn-typegen search load balancer          # find a type name; never guess one
```

In B, put the type list in `cfn/cfn-typegen.toml` and run `cfn-typegen --config cfn-typegen.toml`. Never hand-edit
generated modules (`cfn_types/*.py`). With A, import types from `cfn_typed_sumo.types`.

## 2. Adopt these patterns

### 2.1 One function per stack, config as a frozen dataclass

```python
from dataclasses import dataclass
import cfn_typed as cfn
from cfn_types import sqs

@dataclass(frozen=True)
class OrdersConfig:
    visibility_timeout: int = 180        # things that change the template's SHAPE

def build(config: OrdersConfig = OrdersConfig()) -> cfn.Template:
    params = cfn.Params()
    stage = params.string("Stage", default="dev", allowed_values=["dev", "test", "prod"])
    return {
        "AWSTemplateFormatVersion": "2010-09-09",
        "Parameters": params.declarations(),
        "Resources": {
            "Jobs": sqs.queue(
                VisibilityTimeout=config.visibility_timeout,
                Tags=cfn.tags(Stage=stage),
            ),
        },
        "Outputs": {"JobsUrl": {"Value": cfn.ref("Jobs")}},
    }
```

- `build` is pure: same config, same template. Tests call it directly.
- **One template per stack, never one per stage.** The stage (and any value that only changes a value, not the
  shape) is a CloudFormation parameter: `cfn.Params()` returns the `Ref` to use. Deploy the same file with
  `--parameter-overrides Stage=prod`.
- Several similar stacks: one `build(config)` and one config instance per stack, never copy-pasted modules.
- Read: [A typical project](https://vivainio.github.io/cfn-typed/project-layout/).

### 2.2 Project layout

```text
cfn/
  cfn-typegen.toml     # types in use (B only)
  cfn_types/           # generated, gitignored
  patterns/            # your helper functions
  stacks/              # one module per kind of stack (never name it stacks.py)
  main.py              # cli.main(stacks, schemas=cfn_types)
  tests/test_stacks.py
  rendered/            # templates, committed
```

`main.py`:

```python
import sys
import cfn_types
from cfn_typed import cli
from stacks import orders

def main() -> int:
    return cli.main({**orders.stacks()}, schemas=cfn_types)

if __name__ == "__main__":
    sys.exit(main())
```

Each stack module exposes `def stacks() -> dict[str, StackSpec]: return {"orders": StackSpec(build, out=HERE.parent / "rendered")}`
(`from cfn_typed.cli import StackSpec`). Working copy to imitate:
https://github.com/vivainio/cfn-typed/tree/main/examples/reference/cfn

### 2.3 Patterns are plain functions

A pattern is an ordinary function in the user's repository. No base class, no registry.

- One resource: return that resource.
- Several: return a `Resources` dict, or a **handle** (a small dataclass with a `resources` field and the logical IDs
  and ARNs callers need, e.g. `orders.queue_arn`).
- Logical IDs come from a `name` argument and are documented: `queue_with_dlq("Order")` makes `OrderQueue` and
  `OrderDLQ`. Callers use the handle's fields, not retyped strings.
- Type inputs as `Expr[T]` so a caller can pass a literal or a `Ref`/`GetAtt`.
- Emit optional pieces only when given (no `Tags: []`).
- If a ready-made pattern is close, **copy it into `cfn/patterns/` and change it** rather than wrapping it.
  Catalog: https://vivainio.github.io/cfn-typed/sumo-patterns/ (code in
  `packages/sumo/src/cfn_typed_sumo/`). Once a stack works, drop the `cfn-typed-sumo` dependency and keep
  `cfn-typed`; generate your own types.

Ready-made, from `cfn-typed-sumo` (names change between releases; check the version you pinned):

| Need | Use |
|---|---|
| Queue + dead-letter queue | `queue_with_dlq(name, visibility_timeout=, max_receive_count=)` → `.queue_arn`, `.queue_url`, `.dlq_url` |
| Lambda + role + log group | `constructs.function(name, code=, handler=, runtime=, memory=, timeout=, environment=, statements=)` → `.function`, `.role`, `.log_group` |
| Queue triggers Lambda | `sqs_event_source(function_logical, queue_arn)` |
| Scheduled Lambda | `constructs.schedule(name, "cron(0 3 * * ? *)", function_logical)` |
| Table, key, bucket | `storage.dynamodb_table("pk", "sk")`, `storage.encryption_key(...)`, `storage.secure_bucket(name, key_arn=)` |
| HTTP API (+ JWT) | `http_api(name, function=, routes=["GET /orders"], jwt=)` |
| Alarms | `constructs.lambda_errors_alarm(fn)`, `constructs.queue_backlog_alarm(...)` |
| Static site, VPC, Fargate, load balancer | `static_site`, `constructs.vpc`, `constructs.fargate_service`, `loadbalancer.*` |

Assembly example to copy: https://github.com/vivainio/cfn-typed/blob/main/skills/cfn-typed/resources/example-service.py

### 2.4 Combine fragments with `cfn.combine`, never `|`

```python
"Resources": cfn.combine(orders, worker, {"Table": dynamodb_table("pk", "sk")})
```

`combine` takes dicts and handles and raises on a duplicate logical ID. `|` silently drops one of them. Use
`cfn.merge(a, b)` only for nested defaults/overrides at the edges; it returns untyped `dict[str, Any]`.

### 2.5 Optional properties: a typed `props` variable

```python
props: sqs.QueueProps = {"QueueName": name}
if fifo:
    props["FifoQueue"] = True
sqs.queue(**props)
```

**Never** write `sqs.queue(**({"FifoQueue": True} if fifo else {}))`: `ty` reports an error for every parameter of
the factory. To omit a property by a *template* condition use `cfn.if_(cond, value, cfn.ref("AWS::NoValue"))`.

### 2.6 Shared fragments return the `Props` type, annotated

```python
def lock_down() -> s3.BucketProps:      # annotate the return type
    return {"PublicAccessBlockConfiguration": {"BlockPublicAcls": True, ...}}

s3.bucket(**lock_down(), BucketName=name)   # the caller adds its own keys
```

Without the return annotation a wrong value in the fragment is not reported anywhere. Arrays are invariant `list`:
build tag lists with `cfn.tags(...)`. Read: https://vivainio.github.io/cfn-typed/typing-patterns/

### 2.7 Intrinsics are builders returning plain dicts

`cfn.ref`, `cfn.get_att`, `cfn.sub`, `cfn.join`, `cfn.select`, `cfn.split`, `cfn.find_in_map`, `cfn.if_`,
`cfn.get_azs`, `cfn.base64`, `cfn.cidr`, `cfn.import_value`; conditions `cfn.equals`, `cfn.and_`, `cfn.or_`,
`cfn.not_`, `cfn.condition_ref`. Pseudo parameters: `cfn.ref("AWS::Region")`. Resource attributes are snake_case
keywords: `depends_on`, `deletion_policy`, `update_replace_policy`, `condition`, `metadata`.

Cross-stack values: publish through SSM and read with `params.ssm("VpcId", "/platform/network/vpc-id")` (resolved by
CloudFormation at deploy time; the template stays a pure function of its inputs).

### 2.8 IAM: names, not strings

```python
from cfn_typed.permissions import Sqs
cfn.allow(Sqs.ReceiveMessage, queue_arn)         # a typo is an attribute error
cfn.allow("dynamodb:PutItem", cfn.get_att("Table", "Arn"))   # services without names: a plain string
```

`cfn_typed.grants` has the CDK's permission sets (`grants.Sqs.Queue.consume_messages.on(queue_arn)`). Grants are an
opinion layer: pin the version. Policies are checked for unknown actions, condition operators and keys. Never write
`*` on `*`.

### 2.9 Company conventions as code

- **Mandatory tags**: define the complete set once (`CompanyTags`), apply per service with `tagged(resources, service_tags)`,
  backstop with `untagged(template)`. Read: https://vivainio.github.io/cfn-typed/patterns/mandatory-tags/
- **Rules** (encryption on, DLQ present, retention at least 30 days): `cfn_typed.rules.require(...)`, `forbid(...)`,
  `@each(type)`, collected in `COMPANY_RULES`. Read: https://vivainio.github.io/cfn-typed/patterns/company-rules/

### 2.10 Golden templates in CI

Commit the rendered YAML and fail CI when code and file disagree:

```python
import cfn_types
from cfn_typed import cli
from cfn_typed.testing import assert_matches_file, assert_template_ok
from stacks import orders

def test_orders() -> None:
    assert_matches_file(orders.build(), "rendered/orders.yaml")      # CFN_TYPED_UPDATE=1 pytest accepts a change

def test_orders_ok() -> None:
    assert_template_ok(orders.build(), cfn_types, rules=COMPANY_RULES)

def test_every_stack() -> None:
    stacks = orders.stacks()
    assert cli.main(stacks, schemas=cfn_types, argv=["diff"]) == 0
    assert cli.main(stacks, schemas=cfn_types, argv=["check"]) == 0
```

Read the diff of `rendered/` as part of every review. Keep `cfn-lint` in CI as well: types check shape, not values.

## 3. The loop

After every change, in this order, and fix before moving on:

```sh
ty check                                     # types
CFN_TYPED_UPDATE=1 pytest                    # only when the template change is intended
pytest                                       # golden files, references, quotas, IAM names, runtimes
python main.py check                         # (or: cfn-typed check template.yaml [--schemas cfn_types])
python main.py diff                          # committed rendered/ matches the code
```

Other useful commands: `cfn-typed ls template.yaml -t lambda`, `cfn-typed emit template.yaml -f json`,
`cfn-typegen search <words>`.

## 4. Rules that must not be broken

1. **Never change the logical ID of a stateful resource** (table, bucket, queue, database, stream). A new ID is a
   replacement and deletes the old resource. Set `deletion_policy="Retain"` first; move with a resource import.
2. **Do not invent property, type or permission names.** `cfn-typegen search`, or read the generated module.
3. **Do not execute a change set the user has not seen.** Deploy with `aws cloudformation deploy --template-file ... --stack-name ...`
   only when asked; review with a change set first. cfn-typed produces templates; it does not package or upload code.
4. **Do not silence the checker** (`# type: ignore`, `cast`, dropping to `dict[str, Any]`) to make an error go away.
   Fix the value, or the shape.
5. **Constructs are opinions.** If a default (retention, encryption, tags) does not suit the user, pass the argument or
   copy the pattern and change it. Do not patch the rendered output.
6. **Never put real names, ARNs or account IDs** in a committed fixture or example: invent them.
7. Do not name a module `stacks.py` beside a `stacks/` directory.

## 5. Taking over something that exists

| Starting point | Do |
|---|---|
| A JSON/YAML template | `cfn-typegen --out cfn_types --template template.json`, then `cfn-typed import template.json -o stack.py`. Prove `assert build() == json.load(open("template.json"))`, `ty check`, review a change set before any deploy. Logical IDs and values stay untouched. |
| Serverless Framework | `cfn-typed import --sls template.json -o stack.py`; read https://vivainio.github.io/cfn-typed/deploying/eject-serverless/. Check the zip with `cfn-typed zip app.zip --invoke event.json`. |
| AWS SAM | https://vivainio.github.io/cfn-typed/deploying/sam/ |
| A Step Functions machine | Use `cfn_typed.asl` (`Definition`, `Fragment`, `assert_same_machine`). Put it in `Properties.Definition` as a dict, keep every state name, and make `assert_same_machine(build(), original)` pass before changing anything. |

## 6. Where to look next

| Question | Page |
|---|---|
| How do I wire a Lambda, queue, API, table? | https://vivainio.github.io/cfn-typed/patterns/ |
| What does the core give me? | https://vivainio.github.io/cfn-typed/core/ |
| Intrinsics and conditions | https://vivainio.github.io/cfn-typed/intrinsics/ · https://vivainio.github.io/cfn-typed/conditions/ |
| Testing and CI | https://vivainio.github.io/cfn-typed/testing/ |
| The `cfn-typed` command | https://vivainio.github.io/cfn-typed/cli/ |
| Every sumo pattern | https://vivainio.github.io/cfn-typed/sumo-patterns/ |
| A fuller agent skill (same content as this, longer) | `cfn-typed skill` prints it |
