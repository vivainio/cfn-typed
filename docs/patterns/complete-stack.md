# A complete stack

All the patterns together: an order-processing Lambda fed by a queue, with a
dead-letter queue and a concurrency cap. This is
[`examples/sqs_worker.py`](https://github.com/vivainio/cfn-typed/blob/main/examples/sqs_worker.py).

```python
--8<-- "examples/sqs_worker.py:stack"
```

`SQS_CONSUME` and `DDB_WRITE` are the sample action sets from the
[Lambda execution role](lambda-role.md) page, and the patterns are the ones from the previous
pages.

[See the rendered YAML](../rendered/sqs-worker.md) for the prod stage.

The stage comes from `sys.argv`, so one source file renders every environment:

```sh
python examples/sqs_worker.py prod > prod.json
aws cloudformation deploy --template-file prod.json --stack-name order-processor-prod \
    --capabilities CAPABILITY_IAM
```

## What the checker covers here

- `lambda_.function(...)`: every property name, type and required key.
- `lambda_.FunctionCode(...)` and `lambda_.FunctionEnvironment(...)`: nested shapes.
- `Template`: the top-level structure, and that `Resources` holds real resources.

What it does not cover: that `"OrderQueue"` in `cfn.get_att("OrderQueue", "Arn")`
names a resource that exists. Logical IDs are strings. Two habits make that safe in
practice: build IDs from one `name` inside a pattern, as `queue_with_dlq` does, and
run `cfn-lint` in CI, which does check references.

## Testing it

The template is plain data, so a test is just a function call:

```python
def test_dlq_is_wired() -> None:
    resources = queue_with_dlq("Order")
    policy = resources["OrderQueue"]["Properties"]["RedrivePolicy"]
    assert policy["deadLetterTargetArn"] == get_att("OrderDLQ", "Arn")
```
