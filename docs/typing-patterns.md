---
icon: lucide/shield-check
---

# Typing patterns

The generated types only help if the code around them keeps the types. These are the shapes that work with `ty` at
this time, and the one that looks fine and does not. Everything on this page is in
[`examples/typing_patterns.py`](https://github.com/vivainio/cfn-typed/blob/main/examples/typing_patterns.py), which
`ty check` covers like the rest of the examples.

## Properties that are set only sometimes

When a Python value decides whether a property is there, build the properties in a variable typed with the `Props`
class and add the optional ones with `if`:

```python
--8<-- "examples/typing_patterns.py:optional"
```

Every key is still checked: a misspelled `props["FifoQueu"]` is an error, and so is a value of the wrong type. The
keys are written in the order they are added, which is the order of the rendered template.

Do not splat a conditional dict into the call:

```python
sqs.queue(QueueName=name, **({"FifoQueue": True} if fifo else {}))   # does not type check
```

At this time `ty` cannot tell which key the dict holds, so it checks the dict's values against every parameter of the
factory and reports an error for each, whichever property you meant. The more properties the resource has, the longer
the list.

This is about a value in your Python. To leave a property out depending on a *template* condition, use
[`if_`](intrinsics.md) with `ref("AWS::NoValue")`.

## A fragment is a `Props` dict

Properties that many resources share, such as a public access block, are a function that returns the `Props` type. The
caller adds its own keys and splats the result into the factory, so the fragment and the additions are both checked:

```python
--8<-- "examples/typing_patterns.py:fragment"
```

Annotate the return type. Without it a wrong value in the fragment is not reported anywhere, because the checker
sees a plain `dict` and does not check it against the factory. With it, the error is reported at the `return`.

## One typed config, many stacks

When the same function builds several stacks, the input is a frozen dataclass, not a growing list of keyword
arguments, and a new variant is a new field or a new line of data. The worked example is
[many stacks from one function](project-layout.md#many-stacks-from-one-function).

## Reading the errors

| `ty` rule | What it means here |
|---|---|
| `unknown-argument` | a property name that is not in the resource's `Props`: a typo, or a read-only attribute such as `Arn` |
| `invalid-argument-type` | the value is not `T` or an intrinsic returning `T`; also what a splatted conditional dict produces |
| `missing-argument` | a required property is not set |
| `invalid-key` | the same typo as `unknown-argument`, but on a `props[...]` assignment |
| `invalid-assignment` | the same wrong type as `invalid-argument-type`, but on a `props[...]` assignment |

## Limits of the checker

- `ty` ignores unknown keywords on ordinary TypedDicts, so only the shapes AWS marks closed catch a typo
  ([why](generator.md#why-the-checker-is-strict)).
- Arrays are `list`, which is invariant: a variable typed `list[Tag]` must be `list[Expr[Tag]]` to be passed in.
  `cfn.tags()` returns the right type.
- Types check shape, not values, so they do not replace `cfn-lint`.
