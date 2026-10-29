---
icon: lucide/blocks
---

# cfn-typed

CloudFormation templates as plain Python dicts, checked by your type checker.

There is no CDK, no jsii and no transform. A resource is a `dict`, the template is a
`dict`, and `json.dumps` writes it out. What `cfn-typed` adds is the types:
`cfn-typegen` reads AWS's own resource schemas and emits a `TypedDict` and a
keyword-argument factory for each resource type **you choose**, so a typo, a wrong
type or a missing required property is an error in your editor and in `ty`, long
before CloudFormation sees the template.

```python
from cfn_types import lambda_

lambda_.function(
    FunctionName="f", Role="r", Code=lambda_.FunctionCode(S3Bucket="b"),
    MemorySise=256,   # unknown-argument: did you mean `MemorySize`?
    Timeout="30",     # invalid-argument-type: expected `Expr[int]`, found `str`
)
```

## What is in the box

<div class="grid cards" markdown>

- :lucide-rocket: **[Getting started](getting-started.md)**

    Install, generate the types you need, write your first template.

- :lucide-puzzle: **[Patterns](patterns/index.md)**

    Plain functions that return a resource or a small fragment of several. The
    book's main subject.

- :lucide-cog: **[The generator](generator.md)**

    How `cfn-typegen` chooses types, and what the generated code looks like.

</div>

!!! note "Why dicts?"
    Because the output has to be reviewable data. Every helper in this book returns
    plain dicts you can print, diff and test. Nothing runs at deploy time and
    nothing hides a logical ID.
