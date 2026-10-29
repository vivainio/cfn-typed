# Web stack

A load balancer in front of port 8080, taking its network and tags from SSM parameters through
a shared defaults module. The pieces are explained on the
[load balancer](../patterns/web-entrypoint.md) and
[parameters](../patterns/parameters.md) pages.

```python
--8<-- "examples/web_stack.py:stack"
```

## Rendered YAML

Committed as [`web-stack.yaml`](https://github.com/vivainio/cfn-typed/blob/main/examples/rendered/web-stack.yaml). Note that only the three parameters the
stack uses are declared, and that every value from the defaults is a `!Ref`:

```yaml
--8<-- "examples/rendered/web-stack.yaml"
```
