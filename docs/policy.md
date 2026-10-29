# Policy statements: principals and conditions

An IAM policy statement says *who* may do *what* to *which resource*, optionally *when*. `cfn_typed.policy`
builds them as plain dicts, in the order IAM documents, so the rendered template reads like a policy. Nothing here is
opinion: it builds what you describe. Which actions belong together is the job of the
[grants](grants.md), which use this module.

```python
from cfn_typed import allow, deny
from cfn_typed.policy import ANY, GlobalKeys, aws, bool_

allow(["sqs:ReceiveMessage"], queue_arn)                                   # identity policy: no principal
allow("kms:*", "*", sid="EnableIam", principal=aws(root_arn))              # a key policy
deny("s3:*", [bucket_arn], principal=ANY, condition=bool_(GlobalKeys.SecureTransport, False))
```

## Statements are plain dicts, and checked

You can write a statement three ways, and all of them give the same plain dict:

```python
allow(["sqs:ReceiveMessage"], queue_arn)                                       # the builder
Statement(Effect="Allow", Action=["sqs:ReceiveMessage"], Resource=queue_arn)  # the constructor, awacs-style
{"Effect": "Allow", "Action": ["sqs:ReceiveMessage"], "Resource": queue_arn}  # a literal
```

The type checker checks the last two as well as the builder. A misspelled key (`Efect`, with a "did you mean"
hint for the constructor), a bad `Effect` and a missing `Action` are errors before anything runs. A statement is
one of two closed shapes, because IAM allows `Action` or `NotAction`, never both:

| Type | Has | Made by |
|---|---|---|
| `Statement` | `Action` | `allow(actions)`, `deny(actions)` |
| `NotActionStatement` | `NotAction` | `allow(not_actions=...)`, `deny(not_actions=...)` |

`AnyStatement` is either one, and is what `policy_document` takes. A literal with neither `Action` nor `NotAction`, or with
both, is an error. `Resource` and `NotResource`, and `Principal` and `NotPrincipal`, are also either/or in IAM; the
builders refuse both at once, but the types leave them as optional keys.

## The `Not` forms

`deny(not_actions=[...])` denies everything except the listed actions, which is how to say "nothing but these". The
other fields have the same shape: `not_resource` and `not_principal`.

```python
deny(not_actions=["iam:*", "sts:*"], resource="*", condition=bool_("aws:MultiFactorAuthPresent", False, if_exists=True))
```

## Principals

| Helper | Gives |
|---|---|
| `ANY` | `"*"`: every principal |
| `aws(arn, ...)` | `{"AWS": ...}`: accounts, roles, users |
| `service("lambda.amazonaws.com")` | `{"Service": ...}` |

One value is written as a scalar and several as a list, as the IAM documentation does. Leave `principal` out and the
statement is an identity-policy statement, where the principal is whoever the policy is attached to.

## Conditions

`condition(operator, key, values)` builds one condition, and the common operators have shorthands:
`string_equals`, `string_not_equals`, `string_like`, `string_not_like`, `arn_equals`, `arn_like`, `bool_` and
`ip_address`.

```python
from cfn_typed.policy import GlobalKeys, arn_like, string_not_like

arn_like(GlobalKeys.SourceArn, topic_arn)
string_not_like(GlobalKeys.PrincipalArn, [deploy_role, "arn:aws:iam::123456789012:role/team-*"])
```

- **The operator is a `Literal`.** A misspelled operator is an error before deploy.
- **Booleans and numbers become the strings IAM compares:** `bool_("aws:SecureTransport", False)` is `"false"`.
- **Values may be intrinsics**, such as a `Ref` or a `Sub`.
- **Qualifiers:** `for_any_value=True`, `for_all_values=True` and `if_exists=True` give `ForAnyValue:...`,
  `ForAllValues:...` and `...IfExists`. Asking for both multi-value qualifiers, or `IfExists` with `Null`, is an error.
- **`merge_conditions(a, b)`** combines conditions (all of them must hold), and refuses the same operator and key
  twice instead of silently overwriting one.
- **`GlobalKeys`** is a short, hand-picked list of the global keys the examples and the AWS CDK use
  (`SourceArn`, `SourceAccount`, `PrincipalArn`, `PrincipalOrgID`, `SecureTransport`). It is not complete: for any
  other key, write the string.

## Resource policies from grants

A [grant](grants.md) becomes a *resource-policy* statement when you give it a `principal`:

```python
from cfn_typed import grants
from cfn_typed.policy import aws, service

grants.S3.Bucket.read.on(bucket_arn, principal=aws(reader_role_arn))
grants.Sqs.Queue.send_messages.on(queue_arn, principal=service("sns.amazonaws.com"),
                                  condition=arn_like(GlobalKeys.SourceArn, topic_arn))
```

The same actions and resource shape come out, with a `Principal` added, so it goes in a bucket policy or a queue policy
instead of a role. Use `condition=` to narrow it, as the second example narrows a service principal to one topic.

The three resource policies in the [storage patterns](patterns/storage.md) are three different shapes, and `target`
covers them:

| Policy | `Resource` | How |
|---|---|---|
| bucket, queue, topic policy (their own resource) | the resource | the default, `target="arn"` |
| key policy (inside the key) | `"*"`, the key itself | `target="any"`, with no ARN |
| ECR repository policy | none | `target="omit"`, with no ARN |

A key policy cannot name its own ARN, which would be a circular reference, and a repository policy does not allow a
`Resource` field at all. `target` exists so a grant can produce those correctly.

Two rules keep resource policies honest:

- **No key statement.** `key_arn` is for identity policies. A resource policy cannot carry a statement about another
  resource, so for a key policy you build the key statement yourself, from the grant's `key_actions`.
- **`condition` goes on the main statement,** and `key_condition` on the key statement of an identity grant, for
  conditions such as `kms:ViaService` that belong to the key.

## Trust policies

A role's trust policy says who may assume it. `assume_role_policy` builds it:

```python
from cfn_typed import assume_role_policy
from cfn_typed.policy import aws, service, string_equals

assume_role_policy(service("lambda.amazonaws.com"))
assume_role_policy(aws(partner_account_root), condition=string_equals("sts:ExternalId", external_id))
```

It is a one-statement policy document with `sts:AssumeRole`, ready for `AssumeRolePolicyDocument`. The service principal
is a plain string that you write; there is no list of service names to go stale.

## ARNs

`arn(service, resource)` builds the ARN of a resource in this partition, region and account, with `Fn::Sub` pseudo
parameters, so the same code works in every partition:

```python
arn("dynamodb", "table/orders")   # arn:${AWS::Partition}:dynamodb:${AWS::Region}:${AWS::AccountId}:table/orders
arn("s3", "my-bucket/*")          # arn:${AWS::Partition}:s3:::my-bucket/*
arn("iam", "role/deployer")       # arn:${AWS::Partition}:iam::${AWS::AccountId}:role/deployer
```

Not every ARN has a region and an account. The defaults know the two common exceptions, the way
[awacs](https://github.com/cloudtools/awacs) does: IAM ARNs have no region, and S3 bucket and object ARNs have neither
(S3 access points, jobs and Storage Lens ARNs have both). For any other global service pass `region=False` or
`account=False`.

## Guardrails

A `deny` with a condition is a guardrail, not a grant: it takes access away wherever an allow comes from, so it works
as a backstop behind the grants. The bucket policy in the [storage patterns](patterns/storage.md) is two of them.
Because an explicit deny beats every allow, a deny that is too broad can lock you out of your own resource, so name
your own deploy role in the exceptions.
