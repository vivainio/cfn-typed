# cfn-typed-sumo

[cfn-typed](https://github.com/vivainio/cfn-typed) with the resource types its patterns use
already generated (`cfn_typed_sumo.types`) and a set of reusable patterns
(`cfn_typed_sumo.patterns`): queue with a dead-letter queue, Lambda role, company tags and rules.

```sh
uv add cfn-typed-sumo
```

```python
from cfn_typed_sumo.types import sqs
from cfn_typed_sumo import queue_with_dlq
```
