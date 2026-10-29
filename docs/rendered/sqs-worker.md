# SQS worker

A Lambda triggered by a queue, with a dead-letter queue and a concurrency limit. It is built
from the patterns in this book; see [A complete stack](../patterns/complete-stack.md).

```python
--8<-- "examples/sqs_worker.py:stack"
```

## Rendered YAML

`python examples/sqs_worker.py prod`, as YAML, committed as
[`sqs-worker-prod.yaml`](https://github.com/vivainio/cfn-typed/blob/main/examples/rendered/sqs-worker-prod.yaml):

```yaml
--8<-- "examples/rendered/sqs-worker-prod.yaml"
```
