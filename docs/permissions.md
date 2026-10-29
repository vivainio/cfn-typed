# Permission names

IAM actions are strings, and a misspelled one is not an error. `"sqs:RecieveMessage"` is a perfectly
valid policy that allows nothing, and you find out when the Lambda cannot read its queue.
`cfn_typed.permissions` gives every action a name, so the same mistake is an attribute error the
editor shows as you type:

```python
from cfn_typed.permissions import DynamoDb, Sqs

cfn.allow([Sqs.ReceiveMessage, Sqs.DeleteMessage], [cfn.get_att("OrderQueue", "Arn")])
cfn.allow([DynamoDb.PutItem, DynamoDb.UpdateItem], table_arn)

Sqs.RecieveMessage   # error: no such attribute
```

`Sqs.ReceiveMessage` *is* the string `"sqs:ReceiveMessage"`, so the names go anywhere an action
does and render exactly as before. See the [full list](reference/permissions.md).

## Naming

- The class is the service (`Sqs`, `S3`, `DynamoDb`, `SecretsManager`, ...) and the attribute is
  the action, written as AWS writes it.
- A `*` in the action becomes `_All`: `S3.GetObject_All` is `s3:GetObject*`, and
  `Kms.Create_All` is `kms:Create*`.
- Wildcards that CDK uses are included because that is what its policies grant. Prefer the exact
  names where you can.

## Where the names come from

**They are copied from the [AWS CDK](https://github.com/aws/aws-cdk).** cfn-typed does not
invent a list of permissions. For the major services (S3, DynamoDB, SQS, SNS, Lambda, KMS,
Secrets Manager, SSM, CloudWatch Logs, EventBridge and Kinesis) it takes the action names that the
CDK itself uses when it builds the policies for `grantRead`, `grantWrite`, `grantConsumeMessages`
and the like. The CDK is licensed under Apache-2.0, and the credit is in the module docstring, in the
`NOTICE` file, and here.

Only the names are taken: no CDK code and no documentation text. A script,
`scripts/sync-cdk-permissions.py`, fetches CDK's own files at one pinned commit and extracts
them, and **it refuses to emit a name that it cannot find in those files**, so nothing is typed
in from memory. Bumping the pin is a one-line change followed by a reviewed diff.

## What this is not

- **Not every IAM action.** It is the set of names the CDK uses for these services. For an action that is
  missing, write the string, as before.
- **Not a statement about what is safe to grant.** The names say what actions exist, not which ones belong
  together or on which resources. That is still your decision.
- **Not checked against AWS.** If the CDK has a mistake in a name, so do we, until the next sync.

## Building your own sets

Because the names are plain strings, a set of permissions is just a list, and a list is how you
compose them. The samples used by the examples in this book are three lines each:

```python
--8<-- "examples/permissions.py:permissions"
```

Give the sets a name in your own package, next to the patterns that use them. Which sets belong in a
shared library, and whether to follow the CDK's own named sets such as "consume messages", is open;
the names are the part every approach needs.
