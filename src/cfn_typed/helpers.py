"""Small hand-written helpers that need no generated types."""

from collections.abc import Mapping
from typing import Any

from cfn_typed.base import Tag
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
