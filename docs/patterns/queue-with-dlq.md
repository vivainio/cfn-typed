# Queue with a dead-letter queue

The first multi-resource pattern: two resources that always travel together, with the
redrive policy wired between them. It returns a small handle (`QueueWithDlq`) holding
the logical IDs, ready-made references, and the `resources` to put in the template.

```python
--8<-- "examples/patterns.py:queue_with_dlq"
```

```python
orders = queue_with_dlq("Order", visibility_timeout=180, tags=tags(Stage="prod"))
orders.queue_arn   # GetAtt OrderQueue.Arn
orders.queue_url   # Ref OrderQueue
```

`orders.resources` renders as:

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

- **The handle is the contract.** The caller never rebuilds `"OrderQueue"` by hand:
  `orders.queue_arn` and `orders.queue_url` come from the same IDs the pattern used
  for the `GetAtt`, so the two can never disagree, and a typo is an attribute error.
- **Typed property dicts, not `**kwargs`.** `dlq` and `main` are annotated
  `sqs.QueueProps`, so each key and value is checked, and the optional `Tags` key is
  only added when there are tags. Unpacking them with `**` into the factory keeps the
  output free of empty lists.
- **The tags use one list for both queues**, which is fine because the list is not
  mutated afterwards. If you ever do mutate shared data, copy it first.
