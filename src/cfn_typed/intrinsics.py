"""CloudFormation intrinsic functions and the `Expr` wrapper used by generated types.

Every generated property is `Expr[T]`: either a literal `T` or an intrinsic that
CloudFormation resolves to one at deploy time.
"""

from typing import Any, TypedDict

# "Fn::GetAtt" is not a valid identifier, so these use the functional syntax.
Ref = TypedDict("Ref", {"Ref": str})
GetAtt = TypedDict("GetAtt", {"Fn::GetAtt": list[str]})
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

type Intrinsic = Ref | GetAtt | Sub | Join | Select | Split | If | FindInMap | ImportValue | GetAZs | Base64 | Cidr
type Expr[T] = T | Intrinsic


def ref(logical: str) -> Ref:
    return {"Ref": logical}


def get_att(logical: str, attr: str) -> GetAtt:
    return {"Fn::GetAtt": [logical, attr]}


def sub(template: str, variables: dict[str, Any] | None = None) -> Sub:
    return {"Fn::Sub": [template, variables] if variables else template}


def join(sep: str, parts: list[Any]) -> Join:
    return {"Fn::Join": [sep, parts]}


def import_value(name: Any) -> ImportValue:
    return {"Fn::ImportValue": name}


def arn(service: str, resource: str) -> Sub:
    return sub(f"arn:${{AWS::Partition}}:{service}:${{AWS::Region}}:${{AWS::AccountId}}:{resource}")
