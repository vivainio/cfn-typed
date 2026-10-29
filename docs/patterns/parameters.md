# Parameters as variables

Templates take values from outside: a VPC id, a list of subnets, a stage name. In plain
CloudFormation each is a string you type twice, once in `Parameters` and again in every
`{"Ref": "VpcId"}`. Misspell one and nothing complains until deploy.

`cfn_typed.Params` makes the parameter a **variable**. You declare it once and get back
the `Ref` to use:

```python
params = cfn.Params()
vpc_id = params.ssm("VpcId", "/platform/network/vpc-id")   # a plain {"Ref": "VpcId"}
...
template["Parameters"] = params.declarations()
```

`vpc_id` is an ordinary `Ref` dict, so it is valid anywhere an `Expr[str]` is accepted.
Misspelling the variable is a name error the editor shows immediately, and the string
`"VpcId"` appears exactly once.

## Plain and SSM parameters

| Call | Declares |
|---|---|
| `params.string("Stage", default="dev", allowed_values=[...])` | a `String` parameter |
| `params.number("Size", default=3)` | a `Number` parameter |
| `params.ssm("VpcId", "/path")` | an SSM `String`, resolved by CloudFormation at deploy time |
| `params.ssm_list("Subnets", "/path")` | an SSM `StringList`; the `Ref` is accepted wherever a list of strings is |

SSM values are **not read when you build the template**. The template carries only the
parameter's name in SSM, and CloudFormation looks the value up when the stack is created
or updated and shows it in the change set. That keeps template generation a pure
function of its inputs, which is the property the rest of this book relies on.

Names must be letters and digits only (a CloudFormation rule), and `Params` checks that.
Declaring the same name twice with the same settings is fine and returns the same `Ref`;
declaring it differently raises, so two modules cannot quietly disagree.

## A shared "defaults" library

Organisations usually want one place that knows where the shared network lives, which tags
every stack carries, and so on. That belongs in your **own** package, not in a public one.
Each default is a function that takes the registry and returns variables:

```python
--8<-- "examples/defaults.py:defaults"
```

A stack calls only what it needs:

```python
--8<-- "examples/web_stack.py:stack"
```

- **Only what is called gets declared.** A stack that never calls `network(params)` does not
  get `VpcId` or `PrivateSubnets` in its `Parameters`, so unused defaults never clutter a
  template or count against its parameter limit.
- **The result is a typed bundle.** `net.vpc_id` and `net.private_subnets` autocomplete;
  there is no string to mistype.
- **The paths live in one place.** When the SSM path moves, one line in the defaults
  package changes and every stack follows on its next deploy.
- **Nothing organisation-specific is in `cfn-typed`.** It supplies the mechanism (`Params`);
  your defaults package supplies the names and paths.

The [full rendered stack](../rendered/web-stack.md) has the parameters first, and every use is
`!Ref VpcId`, `!Ref PrivateSubnets`:

```yaml
Parameters:
  VpcId:
    Type: AWS::SSM::Parameter::Value<String>
    Default: /platform/network/vpc-id
  PrivateSubnets:
    Type: AWS::SSM::Parameter::Value<List<String>>
    Default: /platform/network/private-subnets
```

## Values from other stacks

A value exported by another stack needs no registry, because `Fn::ImportValue` is not
declared anywhere. The variable is simply a module-level constant, defined once:

```python
from cfn_typed import import_value

shared_alb_arn = import_value("platform-alb-arn")   # import this name everywhere
```

## Dynamic references and secrets

`cfn.dynamic_ssm("/app/key")` returns the string `{{resolve:ssm:/app/key}}`, and
`dynamic_ssm("/app/password", secure=True)` the `ssm-secure` form. These need no template
parameter, but CloudFormation accepts them only in some properties, and the secure form in
fewer still, so check the resource's documentation before relying on one. For anything
secret, prefer a managed secret and refer to it rather than passing a value through the
template.

## What stays a string

A logical ID in `ref("OrderQueue")` or `get_att(...)` is still a string, because it names a
resource rather than a parameter. Build those from one `name` inside a pattern, as the
other pages do, and keep `cfn-lint` in CI.
