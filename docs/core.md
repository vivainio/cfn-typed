# The core

Everything `cfn_typed` exports is on this page, one line each, with a link to where it is
explained. It is the stable surface: types and mechanics, no opinions. Choices such as
which actions belong together or what a sensible queue looks like live in
[grants](grants.md) and [patterns](patterns/index.md), which build on this and can be
dropped without touching it.

```python
import cfn_typed as cfn
```

## The template

| Name | What it is |
|---|---|
| `Template` | the top-level `TypedDict`: `Resources`, `Parameters`, `Outputs`, `Conditions`, `Mappings`, `Metadata`, `Rules`, `Transform` |
| `Resources` | `dict[str, AnyResource]`, the type of `Template["Resources"]` and of a pattern's fragment |
| `AnyResource` | any generated resource dict: `Type`, optional `Properties`, `DependsOn`, `Condition`, ... |
| `Parameter` | one entry of `Template["Parameters"]`, with every documented attribute (`MinLength`, `AllowedPattern`, `ConstraintDescription`, ...) |
| `Output` | one entry of `Template["Outputs"]` |
| `Tag` | `{"Key": ..., "Value": ...}` |

Resource factories are not here: `cfn-typegen` [generates them](generator.md) for the
resource types you pick.

## Intrinsic functions

Each returns a plain dict, typed as `Expr[T]` so it is accepted wherever a literal of
`T` is. See [Intrinsic functions](intrinsics.md).

| Name | Renders |
|---|---|
| `Expr`, `Intrinsic` | the types: a value or an intrinsic that yields one |
| `ref`, `get_att`, `import_value` | `Ref`, `Fn::GetAtt`, `Fn::ImportValue` |
| `sub`, `join`, `split`, `select`, `base64`, `cidr` | the string and list functions |
| `find_in_map`, `get_azs` | `Fn::FindInMap`, `Fn::GetAZs` |
| `if_`, `equals`, `and_`, `or_`, `not_` | `Fn::If` and the condition functions |
| `ConditionFn`, `condition_ref` | the type of a condition function, and `{"Condition": ...}` |
| `arn` | an `Fn::Sub` ARN with the partition, region and account filled in |

## Policy documents

Builders for IAM policy statements. See [Policy statements](policy.md); the action names
come from [Permission names](permissions.md).

| Name | What it is |
|---|---|
| `allow`, `deny` | build a `Statement` |
| `Statement`, `NotActionStatement`, `AnyStatement` | the statement types |
| `PolicyDocument`, `policy_document` | the document type, and a builder that wraps statements in it |
| `assume_role_policy` | a trust policy for a service or account principal |

Principals and condition builders (`service`, `aws`, `string_equals`, `merge_conditions`, ...) are
in `cfn_typed.policy`, not at the top level. They are listed on the [policy page](policy.md).

## Composing

| Name | What it is |
|---|---|
| `combine` | merge `Resources` fragments and refuse a duplicate logical ID, which `\|` would silently overwrite |
| `HasResources` | the protocol `combine` accepts besides a dict: anything with a `resources` attribute |
| `merge` | deep merge of nested mappings, like Jsonnet's `+`; returns `dict[str, Any]`, so it is unchecked |
| `tags` | `tags(Stage="prod")` as a list of `Tag` |

[Composing fragments](patterns/composing.md) has the reasoning and examples. A pattern's
handle satisfies `HasResources` without importing it.

## Parameters

| Name | What it is |
|---|---|
| `Params` | declare a template parameter once and get back the `Ref` to use: `string`, `number`, `list_of`, `ssm`, `ssm_list`, with an optional AWS-specific `type` |
| `dynamic_ssm` | the `{{resolve:ssm:...}}` string for a value resolved at deploy time |

See [Parameters as variables](patterns/parameters.md).

## Rendering

| Name | What it is |
|---|---|
| `to_json` | `json.dumps` with a default indent |
| `to_yaml` | the same template as readable CloudFormation YAML, with intrinsics in short form |

See [Getting started](getting-started.md#json-or-yaml).

## Testing

In `cfn_typed.testing`, not the top level. See [Testing](testing.md).

| Name | What it is |
|---|---|
| `assert_matches_file` | fail unless the template renders to the committed golden file |
| `assert_references_resolve` | fail on a `Ref`, `GetAtt`, `Sub`, `DependsOn` or condition that names nothing, or on a dependency cycle |
| `assert_constraints_hold` | fail on a property value outside the schema's allowed values, pattern, length, range or item count, following intrinsics where the template decides them |
| `assert_attributes_exist` | fail on an `Fn::GetAtt` (or `${Name.Attr}`) that asks a resource for an attribute its type lacks |
| `assert_combinations_valid` | fail on properties set in a combination the schema rules out: not exactly one of X or Y, none of an at-least-one group, or A set without the B it needs |
| `assert_values_valid` | fail on an `Fn::FindInMap` key the mapping lacks, an `Fn::Select` index outside its list, or a parameter default its own constraints reject |
| `assert_runtimes_supported` | fail on a Lambda runtime AWS has deprecated, saying whether creating or updating is already blocked |
| `assert_iam_valid` | fail on an IAM action `cfn_typed.permissions` does not know, a `Resource` of the wrong service, or an S3 object action on the bucket ARN (and the reverse) |
| `assert_within_limits` | fail on more than 500 resources, 200 parameters, 200 outputs or mappings, a non-alphanumeric logical ID, a long description or an oversized template |
| `assert_nothing_unused` | fail on a parameter, condition or mapping nothing refers to |
| `assert_template_ok` | run all of the checks above in one call, with each problem listed under its check |
