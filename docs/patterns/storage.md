# Encrypted storage

Four resources show up in nearly every data-handling stack, each with a handful of settings that should be
the same every time: an encryption key, a private bucket, a table, and a container repository. These patterns
set those defaults once.

```python
--8<-- "examples/storage.py:imports"
```

## An encryption key

```python
--8<-- "examples/storage.py:encryption_key"
```

- **The key policy only enables IAM.** Access is then granted with ordinary identity policies, for example
  with [grants](../grants.md), instead of listing principals inside the key.
- **`Resource` is `"*"` in the key policy.** In a key policy that means the key itself. Using the key's own
  ARN there is a circular reference, which is why the policy cannot name it.
- **Both resources are retained.** Deleting a key makes everything encrypted with it unreadable, so a stack
  delete should never take it along.

## A private bucket and its policy

```python
--8<-- "examples/storage.py:secure_bucket"
```

- **No bucket name.** CloudFormation picks a unique one, so a replacement never collides with the old bucket.
  The [next page](publishing.md) shows how other stacks find it.
- **Two policy statements, both `Deny`.** A deny for plain HTTP, and with `allowed_principals` a deny for
  everyone not listed. Deny statements win over any allow, so they are a backstop, not a grant.
- **The lockout risk is real.** With `allowed_principals`, a principal that is not on the list cannot use the
  bucket, *including the role that deploys the stack*. The docstring says so, and the
  [example stack](../rendered/data-platform.md) takes the deploy role as a parameter for exactly this reason.
  Wildcards work: `role/team-*` matches a family of roles.

## A table

```python
--8<-- "examples/storage.py:dynamodb_table"
```

On-demand billing and point-in-time recovery are the defaults you almost always want, and deletion protection is
on unless you turn it off. The pattern returns the table itself, so you choose its logical ID.

The key properties come from `cfn_typed.dynamodb.keys`. **It is entirely optional.** `dynamodb.table(...)` takes
`AttributeDefinitions`, `KeySchema` and the indexes as ordinary typed properties, and writing them by hand is
fine, and often clearer for a simple table. `keys` only saves the bookkeeping, mostly once a table has indexes:

```python
table = dynamodb_table("pk", ("ts", "N"), gsis=[gsi("by-user", "user", projection=["name"])])
```

- **A key is `"name"` or `("name", "N")`.** A bare name is a string attribute.
- **`AttributeDefinitions` is derived.** CloudFormation wants every key of the table and of each index declared
  exactly once. `keys` collects them, and refuses one name with two types.
- **The result is a plain `dict`.** Spread it into the factory, `dynamodb.table(**keys(...), BillingMode=...)`, and
  `ty` still checks everything you pass next to it. The keys themselves are correct by construction, so they are
  not typed against the generated shapes: that keeps this module free of generated types, with nothing to drift.
  The arguments are typed, though: an attribute type is `"S"`, `"N"` or `"B"`, and a projection is `"ALL"`,
  `"KEYS_ONLY"` or a list of names.
- **`lsi("name", sk)`** is a local index: it takes the table's hash key.

## A container repository

```python
--8<-- "examples/storage.py:ecr_repository"
```

Immutable tags and scan-on-push, and a pull policy only when you name principals. The pull actions are written with
the [permission names](../permissions.md) (`Ecr.BatchGetImage` and so on), so a typo in one is an error.

## Resource policies

The bucket, key and repository policies above are three different shapes of *resource policy*. They are built with
the [policy helpers](../policy.md), which is why their shapes differ in the table:

| Policy | `Principal` | `Resource` |
|---|---|---|
| bucket policy (its own resource) | `ANY`, narrowed by conditions | the bucket and its objects |
| key policy (inside the key) | an account root | `"*"`, meaning the key itself |
| repository policy | the principals that may pull | none: it applies to its repository |

The two bucket statements are `deny` guardrails with conditions, and the key and repository policies are `allow`
statements. [Grants](../grants.md) can produce the allow side too, with a `principal`.
