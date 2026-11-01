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

<figure markdown="span">
  ![The IQ bell curve meme. In the middle, a crying figure lists CDK, Pulumi, Serverless, SAM and Terraform. At both tails, plain CloudFormation.](assets/cloudformation-bell-curve.jpg){ width="560" }
  <figcaption>Where plain CloudFormation sits on the curve, now with types.</figcaption>
</figure>

[CDK is a Ghetto](cdk-is-a-ghetto.md)

```python
from cfn_types import lambda_

lambda_.function(
    FunctionName="f", Role="r", Code=lambda_.FunctionCode(S3Bucket="b"),
    MemorySise=256,   # unknown-argument: did you mean `MemorySize`?
    Timeout="30",     # invalid-argument-type: expected `Expr[int]`, found `str`
)
```

## The book is bigger than the package

This book looks big, and the package is not. The core is small and plain: dicts, a few intrinsics, a type generator
and a renderer, and you can read it in an afternoon. Most of the pages are not documentation of built-in behavior.
They show how the package solves problems that come up in real stacks (queues with a dead-letter queue, a function
and its role, a release flow, leaving SAM) and are meant as **inspiration**: read one, copy what fits, change what
does not. When a page and your own needs disagree, your needs win. The code on the page is ordinary Python, so there
is nothing to be loyal to.

The book also covers what you have to learn when you move to plain CloudFormation from a build system that did more for
you. SAM, the Serverless Framework and the CDK each take care of things the template does not show: they upload your
code, name the resources, pick the IAM statements, and decide how a release is deployed. Plain CloudFormation does
none of that, so those pages ([uploading code](deploying/package.md), [leaving the Serverless Framework](deploying/eject-serverless.md),
[AWS SAM](deploying/sam.md)) explain what the tool was doing and what you do instead. These are
actually easy things: an upload is a copy to a bucket, a name is a string, and a release is a copy and a `deploy` command. They only
look hard while a tool hides them, and once you have seen each one written out there is little left to learn. That part is
about CloudFormation more than about this package, and it holds whichever way you write the template.

## Facts first, opinions fenced

cfn-typed tries to lock down **facts** and keep them primary: the shapes AWS publishes for every resource, and the
names of IAM actions. A judgement (which actions belong together, what a sensible bucket looks like, which
defaults to pick) is an **opinion**, and opinions live only in modules and pages that are marked as such, so you
can drop them without touching the facts.

| Layer | What it is | How far to rely on it |
|---|---|---|
| [Generated resource types](generator.md) | the shapes AWS publishes | the stable core |
| [The core](core.md) | template types, intrinsics, `combine`, `Params`, rendering | mechanics, no opinion: stable |
| [Permission names](permissions.md) | names of IAM actions, taken from awacs | facts: stable |
| [Policy statements](policy.md) | builders for principals, conditions, allow and deny | mechanics, no opinion: stable |
| [Grants](grants.md) | the CDK's permission sets | **opinion: unstable, marked as such** |
| [Patterns](patterns/index.md) | a secure bucket, a load balancer, ... | **opinion: examples to copy, not an API** |
| [cfn-typed-sumo](sumo.md) | the patterns and generated types as a package | **opinion: a fat library with a volatile API** |

This is deliberately different from systems that bundle the two. In the AWS CDK a construct such as `Bucket` carries
defaults and permission decisions together, and what you get can depend on your CDK version and feature flags;
Pulumi is the engine that applies your change and keeps its own state. Those are real strengths for many teams, and they
are different trade-offs: here the generated shapes never carry a decision, and CloudFormation stays the engine. See the
[comparison](comparison.md), including Troposphere, the closest tool.

## The whole thing in one file

```python
--8<-- "examples/minimal.py:main"
```

## What is in the box

<div class="grid cards" markdown>

- :lucide-rocket: **[Getting started](getting-started.md)**

    Install, generate the types you need, write your first template.

- :lucide-puzzle: **[Patterns](patterns/index.md)**

    Plain functions that return a resource or a small fragment of several. The
    book's main subject.

- :lucide-file-text: **[Rendered examples](rendered/index.md)**

    The YAML each example produces, committed and checked by CI.

- :lucide-scale: **[Comparison](comparison.md)**

    How it differs from Troposphere, the AWS CDK and Pulumi, and what it does not do.

- :lucide-cog: **[The generator](generator.md)**

    How `cfn-typegen` chooses types, and what the generated code looks like.

</div>

!!! note "Why dicts?"
    Because the output has to be reviewable data. Every helper in this book returns
    plain dicts you can print, diff and test. Nothing runs at deploy time and
    nothing hides a logical ID.
