# A complete stack

All the patterns together: an order-processing Lambda fed by a queue, with a
dead-letter queue and a concurrency cap. This is
[`examples/sqs_worker.py`](https://github.com/vivainio/cfn-typed/blob/main/examples/sqs_worker.py).

```python
--8<-- "examples/sqs_worker.py:stack"
```

The role's permissions come from the [grants](../grants.md) (the AWS CDK's permission sets), and the
other parts are the patterns from the previous pages.

[See the rendered YAML](../rendered/sqs-worker.md).

The stage is a template parameter (`Stage`), so one rendered template serves every environment, and the
stage is chosen at deploy time. What would change the template's shape (the table name, the memory size, the
concurrency) is in `WorkerConfig`:

```sh
python examples/sqs_worker.py > template.json
aws cloudformation deploy --template-file template.json --stack-name order-processor-prod \
    --parameter-overrides Stage=prod --capabilities CAPABILITY_IAM
```

## What the checker covers here

- `lambda_.function(...)`: every property name, type and required key.
- `lambda_.FunctionCode(...)` and `lambda_.FunctionEnvironment(...)`: nested shapes.
- `Template`: the top-level structure, and that `Resources` holds real resources.

What it does not cover: that `"OrderQueue"` in `cfn.get_att("OrderQueue", "Arn")`
names a resource that exists. Logical IDs are strings. Two habits make that safe in
practice: build IDs from one `name` inside a pattern and expose them on a handle, as
`queue_with_dlq` does, and
run `cfn-lint` in CI, which does check references.

## Testing it

The template is plain data, so a test is just a function call:

```python
def test_dlq_is_wired() -> None:
    resources = queue_with_dlq("Order").resources
    policy = resources["OrderQueue"]["Properties"]["RedrivePolicy"]
    assert policy["deadLetterTargetArn"] == get_att("OrderDLQ", "Arn")
```
