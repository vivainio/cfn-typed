# cfn-typed-sumo

[cfn-typed](https://github.com/vivainio/cfn-typed) with the resource types its patterns use
already generated (`cfn_typed_sumo.types`) and a set of reusable patterns
(`cfn_typed_sumo.patterns`): queue with a dead-letter queue, Lambda role, company tags and rules.

```sh
uv add cfn-typed-sumo
```

Lots of pre-generated types mean you can try things out quickly: install it and start writing templates.

This is the **fat pattern library**: a lot of batteries, and a **volatile API**. Patterns and names change
between releases, so pin the version. The core, `cfn-typed`, is the package whose API is meant to stay reliable.
See [the book](https://vivainio.github.io/cfn-typed/sumo/).

```python
from cfn_typed_sumo.types import sqs
from cfn_typed_sumo import queue_with_dlq
```
