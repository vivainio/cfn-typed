# Composing fragments

Fragments are dicts, so `|` composes them. Its one weakness is that a duplicate
logical ID silently replaces the first resource:

```python
queue_with_dlq("Order") | queue_with_dlq("Order")   # no error, one queue lost
```

## `combine`

A three-line helper in the examples makes that an error instead:

```python
--8<-- "examples/patterns.py:combine"
```

```python
combine(queue_with_dlq("Order"), queue_with_dlq("Billing"))     # fine
combine(queue_with_dlq("Order"), queue_with_dlq("Order"))       # ValueError: duplicate logical IDs: OrderDLQ, OrderQueue
```

Use `combine` whenever the fragments come from different places, which is when a
clash is easy to cause and hard to spot.

## Deep merge for nested overrides

`|` is shallow. Overriding one environment variable with `defaults | override` would
replace the whole `Environment`. `cfn_typed.merge` merges nested mappings key by key,
like Jsonnet's `+`:

```python
import cfn_typed as cfn

defaults = {"Environment": {"Variables": {"LOG_LEVEL": "info", "STAGE": "dev"}}, "Timeout": 30}
cfn.merge(defaults, {"Environment": {"Variables": {"STAGE": "prod"}}})
# {"Environment": {"Variables": {"LOG_LEVEL": "info", "STAGE": "prod"}}, "Timeout": 30}
```

`merge` returns `dict[str, Any]`, so the type checker no longer checks what you built
with it. Reach for it at the edges (shared defaults, policy documents) and keep
resource construction on the typed factories.
