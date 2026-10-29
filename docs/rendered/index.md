# Rendered examples

The YAML that the examples in this book produce, next to the Python that produces it.

| Example | Shows |
|---|---|
| [Minimal stack](minimal.md) | one queue, one output, the whole program |
| [Web stack](web-stack.md) | a load balancer fragment whose network and tags come from SSM parameters |
| [SQS worker](sqs-worker.md) | a Lambda fed by a queue with a dead-letter queue, built from several patterns |

These are not hand-written. Each file is committed in
[`examples/rendered/`](https://github.com/vivainio/cfn-typed/blob/main/examples/rendered), and the test suite fails if the code stops producing exactly that
text, so what you read here is what the code renders today. See
[Testing with golden templates](../testing.md) for how to do the same in your own repository.
