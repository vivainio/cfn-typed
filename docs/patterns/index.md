# Patterns

A **pattern** is an ordinary function that returns a resource, or a small
*fragment* of several resources. That is the whole idea. There is no base class,
no registry and no construct tree.

```python
def queue_with_dlq(name: str, *, visibility_timeout: int = 30) -> Resources: ...
```

A fragment is a `Resources` dict, a plain `dict[str, AnyResource]`, so you combine
fragments with `|` and drop the result into `Template["Resources"]`.

## Conventions the patterns follow

- **Logical IDs are derived from a `name` argument** and documented:
  `queue_with_dlq("Order")` creates `OrderQueue` and `OrderDLQ`. Callers then use
  `ref("OrderQueue")` or `get_att("OrderQueue", "Arn")`. The names are visible in
  the call, never generated behind your back.
- **A pattern that creates one resource returns that resource's type**
  (`iam.Role`), and a pattern that creates several returns `Resources`.
- **Inputs are typed with `Expr[T]`**, so a caller can pass a literal or a
  `Ref`/`GetAtt`.
- **Optional pieces are only emitted when given.** No `Tags: []` noise in the output.

## Where the code lives

The patterns in this book are not part of the `cfn-typed` package. They are in
[`examples/patterns.py`](https://github.com/vivainio/cfn-typed/blob/main/examples/patterns.py),
they are type-checked and tested like any other code, and every snippet on these
pages is pulled straight from that file. Copy what you need into your project and
change it; they are starting points, not an API.

All of them start from the same imports:

```python
--8<-- "examples/patterns.py:imports"
```

`cfn_types` is the output of `cfn-typegen` for the services used here. This repository
does not contain it; it is generated when the tests run.

| Pattern | Creates |
|---|---|
| [Lambda execution role](lambda-role.md) | one `AWS::IAM::Role` |
| [Queue with a dead-letter queue](queue-with-dlq.md) | `{name}Queue` and `{name}DLQ` |
| [SQS-triggered Lambda](sqs-trigger.md) | one `AWS::Lambda::EventSourceMapping` |
| [Composing fragments](composing.md) | nothing, but how to combine the above safely |
| [A complete stack](complete-stack.md) | all of the above in one template |
