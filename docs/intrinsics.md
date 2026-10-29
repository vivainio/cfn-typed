# Intrinsic functions

CloudFormation's intrinsic functions (`Ref`, `Fn::Sub`, `Fn::Join` and the rest) are how a template refers to things that
are only known at deploy time. Each has a builder in `cfn_typed` that returns the plain dict CloudFormation expects, so
the template stays reviewable data:

```python
from cfn_typed import join, ref

join("/", ["", "orders", ref("Stage")])      # {"Fn::Join": ["/", ["", "orders", {"Ref": "Stage"}]]}
```

Every generated property is `Expr[T]`, which means "a `T`, or any intrinsic". So an intrinsic goes anywhere a value goes,
and you never have to wrap one. Pseudo parameters are plain refs: `ref("AWS::Region")`, `ref("AWS::NoValue")`.

## The functions

| Builder | Emits | Use for |
|---|---|---|
| `ref(name)` | `Ref` | a parameter, a resource, or a pseudo parameter |
| `get_att(resource, attr)` | `Fn::GetAtt` | an attribute of a resource; `attr` may be a `ref(...)` |
| `sub(template, variables=None)` | `Fn::Sub` | substitute `${Name}` and `${Resource.Attr}` in a string |
| `join(separator, parts)` | `Fn::Join` | join strings; `parts` may itself be an intrinsic returning a list |
| `select(index, items)` | `Fn::Select` | one item of a list |
| `split(delimiter, source)` | `Fn::Split` | a string into a list |
| `find_in_map(map, key1, key2)` | `Fn::FindInMap` | a value from the template's `Mappings` |
| `if_(condition, if_true, if_false)` | `Fn::If` | choose by a named condition |
| `get_azs(region="")` | `Fn::GetAZs` | the availability zones; the default is this region |
| `base64(value)` | `Fn::Base64` | encode a string, for example EC2 user data |
| `cidr(block, count, bits)` | `Fn::Cidr` | carve subnets out of a block |
| `import_value(name)` | `Fn::ImportValue` | a value exported by another stack |
| `arn(service, resource)` | `Fn::Sub` | an ARN built from the partition, region and account; see [policy statements](policy.md#arns) |

`if_` is how a property is left out: `if_("IsProd", 5, ref("AWS::NoValue"))` sets it in production and omits it elsewhere.

## Conditions

The condition functions build a template's `Conditions` section, and are not values:

| Builder | Emits |
|---|---|
| `equals(a, b)` | `Fn::Equals` |
| `and_(...)`, `or_(...)` | `Fn::And`, `Fn::Or`; CloudFormation takes between 2 and 10, and the builders refuse anything else |
| `not_(condition)` | `Fn::Not` |
| `condition_ref(name)` | `{"Condition": name}`, a reference to another condition |

`Template["Conditions"]` is typed, so a value that is not a condition function is an error. A resource takes a condition with
its `condition="Name"` keyword, and `if_("Name", ...)` takes the name as a string.

## Everything in one template

This stack uses each function once. It is [`examples/intrinsics_demo.py`](https://github.com/vivainio/cfn-typed/blob/main/examples/intrinsics_demo.py),
type-checked and tested, and the [rendered YAML](rendered/intrinsics.md) is committed and checked by CI:

```python
--8<-- "examples/intrinsics_demo.py:demo"
```

## How they render in YAML

`to_yaml` writes the short forms (`!Ref`, `!Sub`, `!Join` ...). CloudFormation does not allow a short form directly inside
another one, so where that happens the outer function stays in long form: in the example above `Fn::Base64: !Sub ...` and
`Fn::ImportValue: !Sub ...`. An empty string after a short form is written out (`!GetAZs ''`), and a reference to another
condition inside `and_`, `or_` or `not_` stays `Condition: Name`. Parsing the YAML back gives the template you started with;
the test suite checks that for this example.

## What the types do and do not know

The argument types are checked: `join` wants a list of strings or an intrinsic, `sub` wants string variables, and `and_`
wants condition functions. The types do not track what each function **returns**, only that it is an intrinsic. So
`select(...)`, which returns one item, is accepted where a list is expected, and CloudFormation reports that at deploy time.
Keep `cfn-lint` in CI for those.
