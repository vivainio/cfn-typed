"""Check that every `Fn::GetAtt` asks a resource for an attribute its type has.

    problems = find_attribute_problems(template, cfn_types)   # [] when every attribute exists

`cfn_types` is the package `cfn-typegen` generated. Each service module carries an `ATTRIBUTES` table: the read-only and
identifier properties of each resource, which is what the registry says `Fn::GetAtt` can return (`Outer.Inner` for a
nested one). CloudFormation reports a wrong attribute only at deploy time.

Checked: `Fn::GetAtt` in both forms and `${Name.Attr}` in `Fn::Sub`. Not checked: a resource type that was not generated,
an attribute that is itself an intrinsic, and `Outputs.*` on a nested stack. Custom resources are not in the registry, so
they accept any attribute.
"""

import difflib
import re
from collections.abc import Mapping
from types import ModuleType
from typing import Any

from cfn_typed.constraints import _service_module

_SUB_VAR = re.compile(r"\$\{([^}]*)\}")


class _Tables:
    def __init__(self, types: ModuleType | Mapping[str, Any]) -> None:
        self.types = types
        self.cache: dict[str, list[str] | None] = {}

    def get(self, type_name: object) -> list[str] | None:
        if not isinstance(type_name, str):
            return None
        if isinstance(self.types, Mapping):
            return self.types.get(type_name)
        if type_name not in self.cache:
            module = _service_module(self.types, type_name)
            if module is not None and not hasattr(module, "ATTRIBUTES"):
                raise ValueError(f"{module.__name__} has no ATTRIBUTES: regenerate it without --no-constraints")
            self.cache[type_name] = getattr(module, "ATTRIBUTES", {}).get(type_name)
        return self.cache[type_name]


def _valid(attr: str, known: list[str]) -> bool:
    return attr in known or attr.startswith("Outputs.") or any(attr.startswith(k + ".") for k in known)  # a read-only object's members


class _Walker:
    def __init__(self, template: Mapping[str, Any], tables: _Tables) -> None:
        self.types = {name: r.get("Type") for name, r in template.get("Resources", {}).items() if isinstance(r, Mapping)}
        self.tables = tables
        self.problems: list[str] = []

    def _check(self, logical: object, attr: object, path: str, what: str) -> None:
        if not isinstance(logical, str) or not isinstance(attr, str):
            return
        known = self.tables.get(self.types.get(logical))
        if known is not None and not _valid(attr, known):
            close = difflib.get_close_matches(attr, known, n=1)
            hint = f" (did you mean {close[0]!r}?)" if close else ""
            self.problems.append(f"{path}: {what} asks {logical!r} ({self.types[logical]}) for {attr!r}, which is not one of its attributes{hint}")

    def walk(self, node: Any, path: str) -> None:
        if isinstance(node, list):
            for i, item in enumerate(node):
                self.walk(item, f"{path}[{i}]")
            return
        if not isinstance(node, Mapping):
            return
        if len(node) == 1:
            (key, value), = node.items()
            if key == "Fn::GetAtt":
                if isinstance(value, str) and "." in value:
                    logical, attr = value.split(".", 1)
                    self._check(logical, attr, path, "Fn::GetAtt")
                elif isinstance(value, list) and len(value) == 2:
                    self._check(value[0], value[1], path, "Fn::GetAtt")
            elif key == "Fn::Sub":
                text, local = (value[0], value[1]) if isinstance(value, list) and len(value) == 2 else (value, {})
                if isinstance(text, str):
                    for var in _SUB_VAR.findall(text):
                        if "." in var and not var.startswith("!") and not (isinstance(local, Mapping) and var in local):
                            logical, attr = var.split(".", 1)
                            self._check(logical, attr, path, "Fn::Sub")
        for key, value in node.items():
            self.walk(value, f"{path}.{key}")


def find_attribute_problems(template: Mapping[str, Any], types: ModuleType | Mapping[str, Any]) -> list[str]:
    """Every `Fn::GetAtt` in `template` that names an attribute its resource type lacks, one readable line each.

    `types` is the generated package, or a hand-made `{type name: [attribute, ...]}` mapping.
    """
    w = _Walker(template, _Tables(types))
    for section in ("Resources", "Outputs"):
        w.walk(template.get(section, {}), section)
    return w.problems
