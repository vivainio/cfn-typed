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
- **Only exact actions are names.** A pattern such as `s3:GetObject*` is a choice about what to grant, which
  makes it an opinion, so it is not here: the [grants](grants.md) carry the patterns they use, as strings.

## Where the names come from

**They are taken from [awacs](https://github.com/cloudtools/awacs)** (BSD-2-Clause, copyright Mark Peek), a library
that builds its lists from AWS's Service Authorization Reference. For each service that cfn-typed covers it takes
**every** exact action, so the list is complete for those services. The [reference](reference/permissions.md) lists the
services and every name. The credit is in the module docstring, in the `NOTICE` file, with
awacs's licence text in the package, and here.

awacs is used **only by a maintainer script**, `scripts/sync-permissions.py`, which `uv run` gives awacs for the
duration of the run. It is not a dependency of cfn-typed, and the generated module is committed. The script
pins one awacs version, so bumping it is a one-line change followed by a reviewed diff. Before this, the names came from
the AWS CDK's files; awacs is a better source for names because it is complete and comes straight from AWS's reference.

## What this is not

- **Not every service.** It covers a short list of major services (see the [reference](reference/permissions.md)). For any
  other action, write the string, or [add the service](#adding-a-service).
- **Not a statement about what is safe to grant.** The names say what actions exist, not which ones belong
  together or on which resources. That is still your decision.
- **Only as good as awacs.** awacs adds actions as AWS publishes them and keeps the ones it already had, so an
  action that AWS later removes can stay in the list until it is cleaned up.

## Adding a service

If a service you need is missing, **open a pull request** that adds it: one line in `scripts/sync-permissions.py` and
the regenerated module. There is deliberately no command to generate names in your own project, so the list stays one
shared, reviewed thing. The steps are in [CONTRIBUTING.md](https://github.com/vivainio/cfn-typed/blob/main/CONTRIBUTING.md).

Adding a service adds its names only. The [grants](grants.md) are copied from the AWS CDK, so a service gets grants
only if the CDK has them.

## Building your own sets

Because the names are plain strings, a set of permissions is just a list, and a list is how you
compose them. The samples used by the examples in this book are three lines each:

```python
--8<-- "examples/permissions.py:permissions"
```

If you would rather start from the AWS CDK's own sets, such as "consume messages" or "read a bucket", they are in
[grants](grants.md). That layer is opinion, not fact, and is **less permanent** than the names on this page;
give your own sets a name in your own package, next to the patterns that use them, if you want them to stay put.
