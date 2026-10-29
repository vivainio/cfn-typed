# Data platform (consumer)

A role that reads the storage the [producer](data-platform.md) published, through two SSM parameters.

```python
--8<-- "examples/data_consumer.py:consumer"
```

## Rendered YAML

Committed as [`data-consumer.yaml`](https://github.com/vivainio/cfn-typed/blob/main/examples/rendered/data-consumer.yaml):

```yaml
--8<-- "examples/rendered/data-consumer.yaml"
```
