# Queue with a dead-letter queue

The first fragment: two resources that always travel together, with the redrive
policy wired between them.

```python
--8<-- "examples/patterns.py:queue_with_dlq"
```

```python
queue_with_dlq("Order", visibility_timeout=180, tags=tags(Stage="prod"))
```

renders as:

```json
{
  "OrderDLQ":   { "Type": "AWS::SQS::Queue", "Properties": { "Tags": [ ... ] } },
  "OrderQueue": { "Type": "AWS::SQS::Queue", "Properties": {
      "VisibilityTimeout": 180,
      "RedrivePolicy": {
        "deadLetterTargetArn": { "Fn::GetAtt": ["OrderDLQ", "Arn"] },
        "maxReceiveCount": 3
      },
      "Tags": [ ... ] } }
}
```

## Things worth noticing

- **The name is the contract.** The caller knows the IDs are `OrderQueue` and
  `OrderDLQ` because the docstring says so. The pattern itself uses the same
  f-strings for the `GetAtt`, so the two can never disagree.
- **Typed property dicts, not `**kwargs`.** `dlq` and `main` are annotated
  `sqs.QueueProps`, so each key and value is checked, and the optional `Tags` key is
  only added when there are tags. Unpacking them with `**` into the factory keeps the
  output free of empty lists.
- **The tags use one list for both queues**, which is fine because the list is not
  mutated afterwards. If you ever do mutate shared data, copy it first.
