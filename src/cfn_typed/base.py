"""Template-level types and the runtime helper behind every generated factory."""

from collections.abc import Mapping
from typing import Any, Literal, NotRequired, ReadOnly, TypedDict

from cfn_typed.intrinsics import Expr

type DependsOn = str | list[str]
type DeletionPolicy = Literal["Delete", "Retain", "RetainExceptOnCreate", "Snapshot"]
type UpdateReplacePolicy = Literal["Delete", "Retain", "Snapshot"]


class Tag(TypedDict):
    Key: Expr[str]
    Value: Expr[str]


class ResourceAttrs(TypedDict):
    DependsOn: NotRequired[DependsOn]
    DeletionPolicy: NotRequired[DeletionPolicy]
    UpdateReplacePolicy: NotRequired[UpdateReplacePolicy]
    Condition: NotRequired[str]
    Metadata: NotRequired[dict[str, Any]]


class AnyResource(ResourceAttrs):
    """What `Template.Resources` accepts: any generated resource dict."""

    Type: ReadOnly[str]
    Properties: NotRequired[ReadOnly[Mapping[str, Any]]]


class Parameter(TypedDict):
    Type: str
    Default: NotRequired[str | int | float]
    Description: NotRequired[str]
    AllowedValues: NotRequired[list[str]]
    NoEcho: NotRequired[bool]


class Output(TypedDict):
    Value: Expr[str]
    Description: NotRequired[str]
    Export: NotRequired[dict[str, Expr[str]]]
    Condition: NotRequired[str]


type Resources = dict[str, AnyResource]


class Template(TypedDict):
    AWSTemplateFormatVersion: NotRequired[str]
    Description: NotRequired[str]
    Parameters: NotRequired[dict[str, Parameter]]
    Mappings: NotRequired[dict[str, dict[str, Any]]]
    Conditions: NotRequired[dict[str, Any]]
    Resources: Resources
    Outputs: NotRequired[dict[str, Output]]


def build(
    type_name: str,
    props: Mapping[str, Any],
    depends_on: DependsOn | None = None,
    deletion_policy: DeletionPolicy | None = None,
    update_replace_policy: UpdateReplacePolicy | None = None,
    condition: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> Any:
    """Assemble a resource dict. Returns `Any`; each factory declares its precise type."""
    out: dict[str, Any] = {"Type": type_name}
    if props:
        out["Properties"] = dict(props)
    for key, value in (
        ("DependsOn", depends_on),
        ("DeletionPolicy", deletion_policy),
        ("UpdateReplacePolicy", update_replace_policy),
        ("Condition", condition),
        ("Metadata", metadata),
    ):
        if value is not None:
            out[key] = value
    return out
