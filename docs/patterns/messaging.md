# Messaging and events

Fan-out and EventBridge wiring, after the Solutions Constructs `sns-sqs`, `eventbridge-lambda` and
`eventbridge-sqs` patterns. In each of them the resource that sends needs a **resource policy** that names who may
send, and forgetting it is silent: the message is accepted by the sender and never arrives.

```python
--8<-- "examples/integrations.py:imports"
```

## Fan-out

```python
--8<-- "examples/integrations.py:fan_out"
```

```python
fan_out("Orders", ["Billing", "Shipping", "Analytics"])
```

One topic, and a queue with a [dead-letter queue](queue-with-dlq.md) for each subscriber. A slow or broken
subscriber backs up on its own queue instead of affecting the others, and the dead-letter queue catches what it
cannot process. The subscription and the queue policy come from `topic_to_queue` in
[CDK L2 constructs](cdk-l2.md), so this page adds the shape and not another copy of the wiring. Raw message
delivery is on, so a consumer reads the message itself and not an SNS envelope around it.

## EventBridge to a Lambda or a queue

```python
--8<-- "examples/integrations.py:event_rules"
```

```python
event_to_lambda("OrderCreated", "Processor", pattern={"source": ["shop"], "detail-type": ["OrderCreated"]})
event_to_queue("Nightly", "ReportQueue", schedule="cron(0 2 * * ? *)")
```

- **Exactly one of `pattern` and `schedule`.** The rule is either an event match or a clock, and giving both or
  neither is a `ValueError` before anything is deployed.
- **The target alone grants nothing.** A Lambda target needs a `lambda:InvokeFunction` permission, and an SQS
  target needs a queue policy. Both name this rule's ARN, so no other rule can use them.
- **Overlap with `schedule`.** [`schedule`](cdk-l2.md) is the same pattern for a clock only. This one also takes an
  event pattern, and has a queue variant.
- **Encrypted queues.** A queue that uses a customer-managed KMS key also needs a key policy statement for the
  sending service. That is a key policy, so it belongs with the [key](storage.md), not here.
