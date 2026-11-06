# Conditions: building and checking them

A `Condition` narrows a statement to the requests where some fact holds: the caller came over TLS, the source is this
topic, the object has this tag, the time is before the end of the month. IAM writes it as three nested levels, an
*operator*, a *key* and the *values*, and a mistake in any of them is usually not an error. It is a statement that
quietly never matches (an `Allow` that grants nothing), or a `Deny` that never applies. This chapter is about building
conditions so that cannot happen by accident. The builders live in `cfn_typed.policy`; the
[policy chapter](policy.md) covers the statements they go into.

```python
{"StringLike": {"s3:prefix": "home/${aws:username}/*"}}
#  operator       key             value(s)
```

## One condition

`condition(operator, key, values)` builds one, and every operator has a shorthand that fixes the operator and the type of
the values:

```python
from cfn_typed import allow
from cfn_typed.policy import string_like

allow("s3:ListBucket", bucket_arn, condition=string_like("s3:prefix", "home/${aws:username}/*"))
```

```json
{"Effect": "Allow", "Action": "s3:ListBucket", "Resource": "arn:aws:s3:::b",
 "Condition": {"StringLike": {"s3:prefix": "home/${aws:username}/*"}}}
```

| Kind | Builders | Values |
|---|---|---|
| String | `string_equals`, `string_not_equals`, `string_like`, `string_not_like`, `string_equals_ignore_case`, `string_not_equals_ignore_case` | strings |
| ARN | `arn_equals`, `arn_not_equals`, `arn_like`, `arn_not_like` | ARNs, or intrinsics that give one |
| Number | `numeric_equals`, `numeric_not_equals`, `numeric_less_than`, `numeric_less_than_equals`, `numeric_greater_than`, `numeric_greater_than_equals` | `int` |
| Date | `date_equals`, `date_not_equals`, `date_less_than`, `date_less_than_equals`, `date_greater_than`, `date_greater_than_equals` | a timezone-aware `datetime`, or a string such as an epoch |
| Boolean | `bool_` | `bool` |
| Network | `ip_address`, `not_ip_address` | CIDR strings |
| Binary | `binary_equals` | base64 strings |
| Presence | `null` | whether the key is absent |

What the builders do for you:

- **The operator is a `Literal`.** A misspelled operator in `condition(...)` is an error in the type checker, before
  anything runs.
- **Numbers, booleans and dates become the strings IAM compares:** `bool_("aws:SecureTransport", False)` is `"false"`,
  `numeric_less_than("s3:signatureAge", 600000)` is `"600000"`. A float is a `TypeError`.
- **Dates are written in UTC.** `datetime(2026, 1, 1, 12, tzinfo=timezone(timedelta(hours=2)))` becomes
  `"2026-01-01T10:00:00Z"`. A `datetime` with no timezone is a `ValueError`: guessing one in a policy is worse than
  failing.
- **One value is a scalar and several are a list,** as in the IAM documentation. Values may be intrinsics (`ref(...)`,
  `sub(...)`, `get_att(...)`).

```python
from cfn_typed.policy import arn_equals, date_greater_than, ip_address, null

arn_equals("aws:SourceArn", ref("Topic"))                # {"ArnEquals": {"aws:SourceArn": {"Ref": "Topic"}}}
ip_address("aws:SourceIp", ["10.0.0.0/8", "192.0.2.0/24"])
date_greater_than("aws:CurrentTime", datetime(2026, 1, 1, tzinfo=UTC))   # "2026-01-01T00:00:00Z"
null("aws:TokenIssueTime")                                # the key is absent: {"Null": {...: "true"}}
null("aws:TokenIssueTime", False)                         # the key is present
```

## Several keys: `merge_conditions`

A condition block with several entries needs *all* of them to hold. Build them one at a time and merge:

```python
from cfn_typed.policy import GlobalKeys, arn_equals, merge_conditions, string_equals

allow("sqs:SendMessage", queue_arn, principal=service("sns.amazonaws.com"),
      condition=merge_conditions(
          arn_equals(GlobalKeys.SourceArn, ref("Topic")),
          string_equals(GlobalKeys.SourceAccount, ref("AWS::AccountId")),
      ))
```

```json
"Condition": {"ArnEquals": {"aws:SourceArn": {"Ref": "Topic"}},
              "StringEquals": {"aws:SourceAccount": {"Ref": "AWS::AccountId"}}}
```

Two conditions with the same operator and key are an error, not a silent overwrite:
`merge_conditions(string_equals("a", "1"), string_equals("a", "2"))` raises
`condition StringEquals on a is given twice`. Dict `|` would keep the second and drop the first; in a policy
that is a missing restriction, so it is refused. (If you want *either* value, pass a list to one builder.)

## Several values: the qualifiers

Every builder except `null` takes three keyword flags:

| Flag | Writes | Use it when |
|---|---|---|
| `for_any_value=True` | `ForAnyValue:StringEquals` | the key holds a list (a set of tags) and one match is enough |
| `for_all_values=True` | `ForAllValues:StringEquals` | the key holds a list and every element must be in your values |
| `if_exists=True` | `StringEqualsIfExists` | the condition should hold only when the key is in the request |

```python
allow("ec2:RunInstances", "*",
      condition=string_equals("aws:RequestTag/team", ["a", "b"], for_all_values=True, if_exists=True))
# {"ForAllValues:StringEqualsIfExists": {"aws:RequestTag/team": ["a", "b"]}}
```

`for_any_value` with `for_all_values`, and `if_exists` with `null`, are errors, because IAM has no such operators.

Two behaviours cause most surprises, and `if_exists` is the fix for the first:

- **A key that is not in the request makes most operators false.** A `Deny` guarded by `string_equals("aws:RequestTag/x", ...)` does
  not apply to a request with no tag at all. Use `if_exists=True` where an absent key should count as a match, or add a
  `null(...)` condition for the absent case.
- **`ForAllValues` is true for an empty list.** A request with no tags passes `for_all_values=True`. Pair it with
  `null(key, False)` when the key must be present.

## Keys

A key is a string. Global keys start with `aws:`, a service's keys with its prefix (`s3:prefix`,
`sqs:MessageRetentionPeriod`), and some end with a name you choose (`s3:ExistingObjectTag/env`, `aws:RequestTag/team`).
`GlobalKeys` names the few that most policies use, and any other key is just a string:

```python
from cfn_typed.policy import GlobalKeys

GlobalKeys.SourceArn            # "aws:SourceArn"
GlobalKeys.SourceAccount        # "aws:SourceAccount"
GlobalKeys.PrincipalArn         # "aws:PrincipalArn"
GlobalKeys.PrincipalOrgID       # "aws:PrincipalOrgID"
GlobalKeys.SecureTransport      # "aws:SecureTransport"
```

The key is *not* checked by the type checker, since there are thousands and a wrong one is valid Python. That check
happens when the template is built, below.

## Recipes

Each is a statement you can paste, with the condition that makes it the right size.

**Refuse plain HTTP to a bucket**

```python
deny("s3:*", [bucket_arn, sub("${Bucket.Arn}/*")], principal=ANY, condition=bool_(GlobalKeys.SecureTransport, False))
```

**Let one service in, for one source.** A service principal alone lets that service act for *anyone's* resource. Pin it
with `aws:SourceArn` and `aws:SourceAccount` (the `merge_conditions` example above).

**Let a whole organization in**

```python
allow("s3:GetObject", objects_arn, principal=ANY, condition=string_equals(GlobalKeys.PrincipalOrgID, ref("OrgId")))
```

**A folder per user**

```python
allow("s3:ListBucket", bucket_arn, condition=string_like("s3:prefix", "home/${aws:username}/*"))
allow(["s3:GetObject", "s3:PutObject"], sub("${Bucket.Arn}/home/${!aws:username}/*"))
```

`${aws:username}` is an IAM policy variable, and it clashes with `Fn::Sub`'s `${...}`. Write `${!aws:username}`
inside a `sub(...)`, and plain `${aws:username}` in a string that is not.

**Tag-based access**

```python
allow("s3:GetObject", objects_arn, condition=string_equals("s3:ExistingObjectTag/env", "prod"))
allow("ec2:StartInstances", "*", condition=string_equals("aws:ResourceTag/team", ref("Team")))
```

**Require MFA for everything but IAM** (`if_exists`, because a request without MFA has no key at all)

```python
deny(not_actions=["iam:*"], resource="*", condition=bool_("aws:MultiFactorAuthPresent", False, if_exists=True))
```

**A time window**

```python
allow("s3:GetObject", objects_arn, condition=merge_conditions(
    date_greater_than("aws:CurrentTime", datetime(2026, 1, 1, tzinfo=UTC)),
    date_less_than("aws:CurrentTime", datetime(2026, 2, 1, tzinfo=UTC)),
))
```

The two use different operators, so `merge_conditions` accepts them; two `date_less_than` on one key would be refused.

**Only from the corporate network**

```python
deny("*", "*", condition=merge_conditions(
    not_ip_address("aws:SourceIp", ["203.0.113.0/24"]),
    bool_("aws:ViaAWSService", False),
))
```

**An external id on a trust policy**

```python
assume_role_policy(aws(partner_account_root), condition=string_equals("sts:ExternalId", ref("ExternalId")))
```

## What is checked

The builders check the *shape* (operator, value type, qualifiers). The template check, `assert_iam_valid` in your tests or
`find_iam_problems(template)` anywhere, checks the *content* of every statement in the finished template, including ones
you wrote as dict literals:

| Mistake | Message |
|---|---|
| a misspelled operator | `'StringLik' is not a condition operator (did you mean 'StringLike'?)` |
| a misspelled key of a known service | `'s3:prefx' is not a known s3 condition key (did you mean 's3:prefix'?)` |
| a key that none of the statement's actions of that service takes | `'s3:prefix' is not a condition key of any s3 action in the statement; it is for s3:ListBucket, s3:ListBucketVersions` |
| an `Effect` that is not `Allow` or `Deny` | `'Alow' is not 'Allow' or 'Deny'` |

The last-but-one is the one that finds real bugs: `s3:prefix` is a `ListBucket` key, so on a `GetObject` statement the
condition is never true and the statement grants nothing.

The keys come from AWS's Service Authorization Reference, for the services in [permissions](permissions.md), and are
refreshed with `scripts/sync-condition-keys.py`. What is **not** checked:

- global `aws:` keys, and the keys of services outside that list (they are left alone, not flagged);
- a key that is itself an intrinsic, and a statement with `NotAction`, whose actions cannot be listed;
- the *values* of a condition, and whether a key suits its operator (`numeric_less_than` on a string key);
- whether the condition is the right one for what you meant.

A statement listing several actions passes when *any* of them takes the key, because a wildcard such as `s3:Get*` covers
actions that do not. If you list actions explicitly and some do not take the key, give them their own statement: the
condition would be false for those actions, so they would silently get no access (or, in a `Deny`, no restriction).
