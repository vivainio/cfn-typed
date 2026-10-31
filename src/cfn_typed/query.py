"""Look things up in a finished template, for checks that are specific to one company.

    for logical_id, bucket in resources_of(template, "AWS::S3::Bucket").items():
        if prop(bucket, "BucketEncryption.ServerSideEncryptionConfiguration") is None: ...

`resources_of` picks resources by type. `prop` reads a dotted path through nested properties and gives `None` when any step is
missing, or is `Ref: AWS::NoValue`. A list is stepped into by index (`Policies.0.PolicyName`). Neither follows intrinsics:
a value that is a `Ref` or `Fn::If` comes back as that dict, and a rule decides what to do with it.
"""

from collections.abc import Mapping
from typing import Any

_NO_VALUE = {"Ref": "AWS::NoValue"}


def resources_of(template: Mapping[str, Any], *types: str) -> dict[str, Mapping[str, Any]]:
    """The resources of any of the given types, by logical ID."""
    return {k: r for k, r in template.get("Resources", {}).items() if r.get("Type") in types}


def prop(resource: Mapping[str, Any], path: str) -> Any:
    """The property at the dotted `path` below `Properties`, or `None` when it is absent or `Ref: AWS::NoValue`."""
    node: Any = resource.get("Properties")
    for step in path.split("."):
        if isinstance(node, Mapping):
            node = node.get(step)
        elif isinstance(node, list) and step.isdigit() and int(step) < len(node):
            node = node[int(step)]
        else:
            return None
    return None if node == _NO_VALUE else node
