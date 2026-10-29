# SQS-triggered Lambda

A single resource that connects a queue to a function.

```python
--8<-- "examples/patterns.py:sqs_event_source"
```

```python
sqs_event_source("Processor", cfn.get_att("OrderQueue", "Arn"), batch_size=5)
```

## Things worth noticing

- **The function is named, not passed.** `function_logical` is a logical ID, and the
  pattern turns it into `get_att(function_logical, "Arn")`. That keeps the call
  site short, at the cost of a string the checker cannot verify. It is the standard
  trade-off of plain dicts, and the next page shows how to guard the related
  duplicate-ID mistake.
- **The queue is an `Expr[str]`.** Pass a `get_att` for a queue in the same
  template, or a literal ARN or `import_value(...)` for one in another stack.
- **It is deliberately small.** A pattern that wraps one resource is still worth
  having when the wiring (here, `FunctionName` from a `GetAtt`) is what you keep
  retyping.
