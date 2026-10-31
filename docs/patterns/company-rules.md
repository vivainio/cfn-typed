# Company rules

The built-in [checks](../testing.md#more-checks-on-the-finished-template) say whether a template is valid. A company also
has rules that are not about validity: buckets are encrypted, queues have a dead-letter queue, nobody gets `*` on `*`.
They are one more layer on the same checks, and run in the same call.

```python
--8<-- "packages/sumo/src/cfn_typed_sumo/patterns.py:company_rules"
```

A **rule** is a function from the finished template to a list of problems, one readable line each. That is the shape
of every `find_*_problems` in the library, so a rule can always be written by hand. Most are one of three forms, so
`cfn_typed.rules` has a constructor for each:

| Form | Reads as |
|---|---|
| `require(type, path, equals= / one_of= / at_least= / at_most= / matches=)` | every resource of that type sets `path`, and the value meets the conditions |
| `forbid(type, path, equals= / one_of=)` | no resource of that type sets `path`, or sets it to that value |
| `@each(type)` on a function of one resource | anything else about a single resource; return a problem, a list, or `None` |

`type` is one type or a sequence of them, and `unless=lambda logical_id, resource: ...` exempts a resource. A rule made by
`require` or `forbid` is named after what it demands, so a failure says which rule it was. A rule that has to look at
several resources at once (every queue needs a dead-letter queue somewhere) is a plain function, as `queues_have_a_dead_letter_queue` is.

```python
def test_orders_stack() -> None:
    assert_template_ok(build("prod"), cfn_types, rules=COMPANY_RULES)
```

```text
AssertionError: the template has problems:
  [references] Resources.Worker.Properties.Role: Fn::GetAtt refers to 'ExecutionRol', ...
  [AWS::S3::Bucket.BucketEncryption required] Bucket: BucketEncryption is not set
  [AWS::Logs::LogGroup.RetentionInDays at_least=30 required] Logs: RetentionInDays is 7, expected at least 30
```

Each problem is listed under the rule's function name, next to the built-in ones. `find_all_problems(template, rules=...)`
returns the same as a dict.

## Helpers for writing rules

For a plain function, `cfn_typed.query` has two. Neither follows intrinsics:

| Helper | Does |
|---|---|
| `resources_of(template, *types)` | the resources of those types, by logical ID |
| `prop(resource, "A.B.0.C")` | the value at a dotted path below `Properties`; `None` when a step is missing or is `Ref: AWS::NoValue` |

## Things worth noticing

- **Rules read the finished template, not your code.** They also catch resources from a pattern someone else wrote or
  a fragment copied from another team. Use [`tagged`](mandatory-tags.md) to build the right thing and a rule to prove it.
- **A value that is an intrinsic is set, but cannot be compared.** `require(..., at_least=30)` accepts a `Ref` for the value:
  it is decided at deploy time, and a rule is silent about what it cannot read. In your own functions `prop` gives you the
  `Ref` dict, so decide there whether to skip it or to fail.
- **Make your own constructor** the same way the library does: a function that returns a rule, with `__name__` set so a
  failure says which one it was.
- **Test the rules themselves** on a small bad template, as `tests/test_patterns.py` does: each rule should fail on
  something and pass on the example patterns.
- **Share the list, not a framework.** Put `COMPANY_RULES` in the package that holds the company's patterns
  (see [distributing](../distributing.md)), and every repository gets the same layer by passing it in.
