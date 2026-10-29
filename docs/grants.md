# Grants: the CDK's permission sets

!!! warning "An opinion layer, less permanent than the rest"
    **Everything on this page is opinion, not fact, and it is the least permanent part of cfn-typed.**

    | Layer | What it is | How much to rely on it |
    |---|---|---|
    | Generated resource types | the shapes AWS publishes, regenerated from its schemas | the stable core |
    | [Permission names](permissions.md) | the names of IAM actions, copied from the AWS CDK | stable: facts, and mostly additive |
    | **Grants (this page)** | which actions belong together, and on which resources | **unstable: a judgement that can change** |

    A grant can change whenever the AWS CDK changes its mind, can be renamed or removed in any release, and
    may move to a separate package. If you depend on one, **pin the version of cfn-typed**, or copy the set
    you rely on into your own code. The sets are the CDK's opinions, not AWS guidance and not a
    statement of what is right for your system.

A *grant* is a named set of IAM actions together with the resources it applies to. It is what the AWS CDK
calls `grantRead`, `grantWrite`, `grantConsumeMessages` and so on, and this layer copies the CDK's decisions
for the major services and says so.

```python
from cfn_typed import grants

grants.Sqs.Queue.consume_messages.on(queue_arn)
grants.S3.Bucket.read.on(bucket_arn, key_arn=my_key)
grants.DynamoDb.Table.read_write_data.on(table_arn, indexes=True)
```

`.on(...)` returns a list of statements. Every grant is listed under [reference](reference/grants.md).

## What a grant carries

1. **The actions.** `Sqs.Queue.consume_messages` is the CDK's set: `ReceiveMessage`, `ChangeMessageVisibility`,
   `GetQueueUrl`, `DeleteMessage` and `GetQueueAttributes`. They are built from the
   [permission names](permissions.md), so a grant cannot contain an action that is not a known name.
2. **Where they apply.** The ARN you pass is expanded the way the CDK does it:

    | Shape | Applies to | Example |
    |---|---|---|
    | `arn` | the ARN | queues, topics, functions, keys, secrets |
    | `arn_and_objects` | the ARN and `{arn}/{keys}` (`keys` defaults to `*`) | `S3.Bucket.read`, `write`, `read_write` |
    | `objects` | only `{arn}/{keys}` | `S3.Bucket.put`, `delete`, `put_acl` |
    | `arn_and_indexes` | the ARN, and with `indexes=True` also `{arn}/index/*` | DynamoDB table grants |
    | `any` | `*`; takes no ARN | `DynamoDb.Table.list_streams` |

    When the ARN is an intrinsic such as `get_att("Bucket", "Arn")`, the child ARNs are built with `Fn::Join`.
3. **Key actions.** Pass `key_arn=` when the resource is encrypted with your own KMS key and you get a second
   statement allowing the key actions, for example `kms:Decrypt` for a read. It is left out when you pass no key,
   and ignored for grants that need none.

## Putting the statements somewhere

The statements have **no `Principal`**. They are identity-policy statements, and a grant knows nothing about
where they end up, so there is no side effect on a role as in the CDK:

```python
stmts = [
    *grants.Sqs.Queue.consume_messages.on(get_att("OrderQueue", "Arn")),
    *grants.DynamoDb.Table.write_data.on(arn("dynamodb", "table/orders")),
]

lambda_role("orders-prod", stmts)                            # inline on a role (the pattern in this book)
iam.managed_policy(PolicyDocument=policy_document(stmts),    # or a managed policy
                   Roles=[ref("WorkerRole")])
```

The [SQS worker example](rendered/sqs-worker.md) uses exactly this, and its rendered YAML shows the result.

## Where they come from

**They are copied from the [AWS CDK](https://github.com/aws/aws-cdk)** (Apache-2.0), at one pinned commit, and the
credit is in the module docstring, in the `NOTICE` file and here. For services where the CDK keeps a `grants.json`,
the sets are taken as they are. For the rest (S3, DynamoDB, KMS, Kinesis, Lambda, Secrets Manager) the CDK composes
them in code from constants, and `scripts/sync-cdk-grants.py` records how, citing the method it read.

The script **refuses to emit anything it cannot find in those CDK files**, so nothing is typed in from memory.
No CDK code or documentation text is included. Bumping the pin is a one-line change, followed by a
reviewed diff of the generated module, and, because the example stack's [rendered
YAML](rendered/sqs-worker.md) is committed, by a test failure that shows exactly what changed in the policy.

## What it does not do

- **Resource policies.** A queue or bucket policy that names a principal needs a `Principal` and a different
  `Resource`. The CDK does that in `addToPrincipalOrResource`; this layer is identity statements only.
- **Service principals as grantees**, for example letting S3 invoke a Lambda. That is an `AWS::Lambda::Permission`
  resource, not a policy statement.
- **The CDK's other behaviour.** `Table.stream_read` here grants the stream actions on the stream ARN; the CDK also
  grants `list_streams`, so use both. S3 uses the non-legacy put actions. Lambda `invoke` is on the function ARN;
  the CDK's version and function-URL variants are not included.
- **Mutation.** Nothing here touches a role. If two resources refer to each other through policies, avoiding the
  circular dependency is up to how you wire the template.
