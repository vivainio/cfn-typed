"""CloudFormation intrinsic functions, the `Expr` wrapper used by generated types, and a builder for each function.

Every generated property is `Expr[T]`: either a literal `T` or an intrinsic that CloudFormation resolves to one at
deploy time. Each builder returns the plain dict CloudFormation expects, so the template stays reviewable data:

    join("/", ["", "orders", ref("Stage")])        # {"Fn::Join": ["/", ["", "orders", {"Ref": "Stage"}]]}
    if_("IsProd", 120, 30)                          # {"Fn::If": ["IsProd", 120, 30]}

The condition functions (`equals`, `and_`, `or_`, `not_`) are for a template's `Conditions` section, and are not values.
Pseudo parameters are plain refs: `ref("AWS::Region")`, `ref("AWS::NoValue")`.

The types track which intrinsic you used, not what it returns: `select(...)` is accepted where a list is expected, and
CloudFormation reports that at deploy time.
"""

from collections.abc import Mapping
from typing import Any, TypedDict

# "Fn::GetAtt" is not a valid identifier, so these use the functional syntax.
Ref = TypedDict("Ref", {"Ref": str})
GetAtt = TypedDict("GetAtt", {"Fn::GetAtt": list[str | Ref]})  # the attribute name may itself be a Ref
Sub = TypedDict("Sub", {"Fn::Sub": str | list[Any]})
Join = TypedDict("Join", {"Fn::Join": list[Any]})
Select = TypedDict("Select", {"Fn::Select": list[Any]})
Split = TypedDict("Split", {"Fn::Split": list[Any]})
If = TypedDict("If", {"Fn::If": list[Any]})
FindInMap = TypedDict("FindInMap", {"Fn::FindInMap": list[Any]})
ImportValue = TypedDict("ImportValue", {"Fn::ImportValue": Any})
GetAZs = TypedDict("GetAZs", {"Fn::GetAZs": Any})
Base64 = TypedDict("Base64", {"Fn::Base64": Any})
Cidr = TypedDict("Cidr", {"Fn::Cidr": list[Any]})

# Condition functions: they belong in the `Conditions` section (and are what a condition name refers to), not in values.
Equals = TypedDict("Equals", {"Fn::Equals": list[Any]})
And = TypedDict("And", {"Fn::And": list[Any]})
Or = TypedDict("Or", {"Fn::Or": list[Any]})
Not = TypedDict("Not", {"Fn::Not": list[Any]})
ConditionRef = TypedDict("ConditionRef", {"Condition": str})

type Intrinsic = Ref | GetAtt | Sub | Join | Select | Split | If | FindInMap | ImportValue | GetAZs | Base64 | Cidr
type Expr[T] = T | Intrinsic
type ConditionFn = Equals | And | Or | Not | ConditionRef


def ref(logical: str) -> Ref:
    """The value of a parameter or resource (its Ref), or a pseudo parameter such as `ref("AWS::Region")`."""
    return {"Ref": logical}


def get_att(logical: str, attr: str | Ref) -> GetAtt:
    """An attribute of a resource, `get_att("Queue", "Arn")`. The attribute name may be a `ref(...)`."""
    return {"Fn::GetAtt": [logical, attr]}


def sub(template: str, variables: Mapping[str, Expr[str]] | None = None) -> Sub:
    """Substitute `${Name}` (parameters, resources, pseudo parameters) and `${Resource.Attr}` in a string."""
    return {"Fn::Sub": [template, dict(variables)] if variables else template}


def join(sep: str, parts: Expr[list[Expr[str]]]) -> Join:
    """Join strings with a separator. `parts` may itself be an intrinsic that returns a list."""
    return {"Fn::Join": [sep, parts]}


def select(index: int | Expr[str], items: Expr[list[Expr[str]]]) -> Select:
    """One item of a list: `select(0, get_azs())` is the first availability zone."""
    return {"Fn::Select": [index, items]}


def split(delimiter: str, source: Expr[str]) -> Split:
    """Split a string into a list: `select(1, split(",", "a,b,c"))`."""
    return {"Fn::Split": [delimiter, source]}


def find_in_map(map_name: str, top_key: Expr[str], second_key: Expr[str]) -> FindInMap:
    """A value from the template's `Mappings`: `find_in_map("Sizes", ref("Stage"), "Memory")`."""
    return {"Fn::FindInMap": [map_name, top_key, second_key]}


def if_(condition: str, if_true: Any, if_false: Any) -> If:
    """`if_true` when the named condition holds, otherwise `if_false`. Use `ref("AWS::NoValue")` to leave a property out."""
    return {"Fn::If": [condition, if_true, if_false]}


def get_azs(region: Expr[str] = "") -> GetAZs:
    """The availability zones of a region; the empty string, the default, means this stack's region."""
    return {"Fn::GetAZs": region}


def base64(value: Expr[str]) -> Base64:
    """Base64-encode a string, for example EC2 user data."""
    return {"Fn::Base64": value}


def cidr(ip_block: Expr[str], count: int | Expr[str], cidr_bits: int | Expr[str]) -> Cidr:
    """Carve `count` subnets of `cidr_bits` host bits out of a block, as a list of CIDR blocks."""
    return {"Fn::Cidr": [ip_block, count, cidr_bits]}


def import_value(name: Expr[str]) -> ImportValue:
    """A value exported by another stack."""
    return {"Fn::ImportValue": name}


# -- condition functions -------------------------------------------------------------------------------------------


def equals(left: Expr[str], right: Expr[str]) -> Equals:
    return {"Fn::Equals": [left, right]}


def and_(*conditions: ConditionFn) -> And:
    """All of the conditions hold. CloudFormation takes between 2 and 10."""
    if not 2 <= len(conditions) <= 10:
        raise ValueError(f"Fn::And needs between 2 and 10 conditions, got {len(conditions)}")
    return {"Fn::And": list(conditions)}


def or_(*conditions: ConditionFn) -> Or:
    """Any of the conditions holds. CloudFormation takes between 2 and 10."""
    if not 2 <= len(conditions) <= 10:
        raise ValueError(f"Fn::Or needs between 2 and 10 conditions, got {len(conditions)}")
    return {"Fn::Or": list(conditions)}


def not_(condition: ConditionFn) -> Not:
    return {"Fn::Not": [condition]}


def condition_ref(name: str) -> ConditionRef:
    """Refer to another condition by name, inside `and_`, `or_` or `not_`."""
    return {"Condition": name}


# S3 ARNs for buckets and objects have no region and no account (`arn:aws:s3:::bucket/key`); these resource kinds do.
_S3_REGIONAL = ("accesspoint/", "job/", "storage-lens/")


class _Arn:
    """Builds ARNs in this partition, region and account through `Fn::Sub` pseudo parameters.

    Call it for any service, or use the method for a resource kind whose format is easy to get wrong:

        arn("dynamodb", "table/orders")   # arn:${AWS::Partition}:dynamodb:${AWS::Region}:${AWS::AccountId}:table/orders
        arn.bucket("data")                 # arn:${AWS::Partition}:s3:::data
        arn.function("handler")            # arn:${AWS::Partition}:lambda:${AWS::Region}:${AWS::AccountId}:function:handler

    Names may contain `${...}` substitutions, as in any `Fn::Sub`.
    """

    def __call__(self, service: str, resource: str, *, region: bool | str | None = None, account: bool | str | None = None) -> Sub:
        """The ARN of `resource` in `service`.

        Not every ARN has a region and an account, and the defaults know the two common exceptions, as awacs does
        (https://github.com/cloudtools/awacs): IAM ARNs have no region, and S3 bucket and object ARNs have neither.
        For any other global service pass `region=False` or `account=False`; pass a string to name another region or
        account, for example `account="111111111111"`.
        """
        s3_plain = service == "s3" and not resource.startswith(_S3_REGIONAL)
        if region is None:
            region = not (service == "iam" or s3_plain)
        if account is None:
            account = not s3_plain
        region_part = region if isinstance(region, str) else "${AWS::Region}" if region else ""
        account_part = account if isinstance(account, str) else "${AWS::AccountId}" if account else ""
        return sub(f"arn:${{AWS::Partition}}:{service}:{region_part}:{account_part}:{resource}")

    def bucket(self, name: str) -> Sub:
        return self("s3", name)

    def object(self, bucket: str, key: str = "*") -> Sub:
        """Objects in a bucket; every object by default."""
        return self("s3", f"{bucket}/{key}")

    def function(self, name: str, qualifier: str | None = None) -> Sub:
        """A Lambda function, optionally a version or alias."""
        return self("lambda", f"function:{name}" + (f":{qualifier}" if qualifier else ""))

    def table(self, name: str) -> Sub:
        return self("dynamodb", f"table/{name}")

    def table_index(self, table: str, index: str) -> Sub:
        return self("dynamodb", f"table/{table}/index/{index}")

    def queue(self, name: str) -> Sub:
        return self("sqs", name)

    def topic(self, name: str) -> Sub:
        return self("sns", name)

    def role(self, name: str, path: str = "/") -> Sub:
        """An IAM role; `path` is `/` unless the role was created under another."""
        return self("iam", f"role{path.rstrip('/')}/{name}")

    def policy(self, name: str, path: str = "/") -> Sub:
        """A customer managed IAM policy."""
        return self("iam", f"policy{path.rstrip('/')}/{name}")

    def secret(self, name: str) -> Sub:
        """A Secrets Manager secret. Real secret ARNs end in a random suffix, so end `name` with `-*` to match it."""
        return self("secretsmanager", f"secret:{name}")

    def parameter(self, name: str) -> Sub:
        """An SSM parameter; the leading slash of `name` is dropped, as the ARN has none."""
        return self("ssm", f"parameter/{name.lstrip('/')}")

    def log_group(self, name: str, streams: bool = False) -> Sub:
        """A CloudWatch Logs log group, or with `streams` the log streams inside it."""
        return self("logs", f"log-group:{name}" + (":*" if streams else ""))

    def key(self, key_id: str) -> Sub:
        """A KMS key."""
        return self("kms", f"key/{key_id}")


arn = _Arn()
