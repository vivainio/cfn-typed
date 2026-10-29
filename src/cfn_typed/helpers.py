"""Small hand-written helpers that need no generated types."""

from collections.abc import Mapping
from typing import Any

from cfn_typed.base import AnyResource, HasResources, Resources, Tag
from cfn_typed.intrinsics import Expr


def tags(**kv: str) -> list[Expr[Tag]]:
    return [{"Key": k, "Value": v} for k, v in kv.items()]


def merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    """Deep merge like Jsonnet's `+`: nested mappings merge key by key, anything else is replaced.

    `base | override` is shallow and would replace a whole `Environment`.
    """
    out = dict(base)
    for key, value in override.items():
        existing = out.get(key)
        out[key] = merge(existing, value) if isinstance(existing, Mapping) and isinstance(value, Mapping) else value
    return out


def combine(*fragments: Resources | HasResources) -> Resources:
    """Merge fragments like `|`, but refuse to silently overwrite a logical ID.

    Each fragment is a `Resources` dict or a handle with a `resources` attribute.
    """
    out: dict[str, AnyResource] = {}
    for fragment in fragments:
        resources = fragment if isinstance(fragment, dict) else fragment.resources
        clash = out.keys() & resources.keys()
        if clash:
            raise ValueError(f"duplicate logical IDs: {', '.join(sorted(clash))}")
        out |= resources
    return out
