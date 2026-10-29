# Lambda execution role

Every Lambda needs a role that it can assume and that can write logs. The
interesting part is the extra permissions, so that is the argument.

```python
--8<-- "examples/patterns.py:lambda_role"
```

Use it by passing the statements the function needs. The action sets below are samples to
copy and adjust, kept in `examples/permissions.py`; they are not part of the library:

```python
--8<-- "examples/permissions.py:permissions"
```

```python
lambda_role("order-processor-prod", [
    cfn.allow(SQS_CONSUME, [cfn.get_att("OrderQueue", "Arn")]),
    cfn.allow(DDB_WRITE, cfn.arn("dynamodb", "table/orders-prod")),
])
```

## Things worth noticing

- **It returns `iam.Role`**, not `dict`. The generated type knows `Policies` takes a
  list of `iam.RolePolicy`, so a misspelled `PolicyDocumnet` is an error here, in the
  pattern, rather than in every caller.
- **`allow` and `Statement` come from `cfn_typed`.** `Effect` is limited to
  `"Allow"` or `"Deny"`, and `Resource` accepts a literal or an intrinsic.
- **`arn()` builds a `Fn::Sub`** with the partition, region and account filled in
  by CloudFormation, so the same code works in every partition.
- **The log group wildcard is scoped to the function prefix**, not `*`. Least
  privilege is cheaper to write once in a pattern than to remember in every stack.
