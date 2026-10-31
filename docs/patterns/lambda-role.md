# Lambda execution role

Every Lambda needs a role that it can assume and that can write logs. The
interesting part is the extra permissions, so that is the argument.

```python
--8<-- "packages/sumo/src/cfn_typed_sumo/patterns.py:lambda_role"
```

Use it by passing the statements the function needs. The [grants](../grants.md) give you
statements for common cases; they are the AWS CDK's opinions, so treat them as less permanent than the
rest of this book:

```python
lambda_role("order-processor-prod", [
    *grants.Sqs.Queue.consume_messages.on(cfn.get_att("OrderQueue", "Arn")),
    *grants.DynamoDb.Table.write_data.on(cfn.arn.table("orders-prod")),
])
```

Or write your own with the [permission names](../permissions.md), which are plain strings, so a typo is an
attribute error:

```python
cfn.allow([Sqs.ReceiveMessage, Sqs.DeleteMessage], [cfn.get_att("OrderQueue", "Arn")])
```

## Things worth noticing

- **It returns `iam.Role`**, not `dict`. The generated type knows `Policies` takes a
  list of `iam.RolePolicyProperty`, so a misspelled `PolicyDocumnet` is an error here, in the
  pattern, rather than in every caller.
- **`allow` and `Statement` come from `cfn_typed`.** `Effect` is limited to
  `"Allow"` or `"Deny"`, and `Resource` accepts a literal or an intrinsic.
- **`arn()` and its methods, like `arn.table(...)`, build a `Fn::Sub`** with the partition, region and account filled in
  by CloudFormation, so the same code works in every partition.
- **The log group wildcard is scoped to the function prefix**, not `*`. Least
  privilege is cheaper to write once in a pattern than to remember in every stack.
