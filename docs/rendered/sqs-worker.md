# SQS worker

A Lambda triggered by a queue, with a dead-letter queue and a concurrency limit. It is built
from the patterns in this book; see [A complete stack](../patterns/complete-stack.md).

```python
--8<-- "examples/sqs_worker.py:stack"
```

## Rendered YAML

`cfn.to_yaml(build())`, committed as
[`sqs-worker.yaml`](https://github.com/vivainio/cfn-typed/blob/main/examples/rendered/sqs-worker.yaml):

```yaml
--8<-- "examples/rendered/sqs-worker.yaml"
```
