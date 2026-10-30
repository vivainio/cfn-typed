"""Check the values a template looks up or declares: `Fn::FindInMap` keys, `Fn::Select` indexes and parameter defaults.

    problems = find_value_problems(template)   # [] when every lookup and default is valid

- `Fn::FindInMap`: each top-level and second-level key must exist in the mapping. A key is a literal, or a `Ref` to a
  parameter, whose allowed values (else its default, see `defaults`) are each tried. A `DefaultValue` in the fourth
  argument makes a missing key fine. A mapping that does not exist is reported by `cfn_typed.references`.
- `Fn::Select` with a literal index and a literal list: the index must be inside the list.
- Parameters: a `Default` must be one of `AllowedValues`, match `AllowedPattern` entirely, and be within
  `MinLength`/`MaxLength` or, for a `Number`, `MinValue`/`MaxValue`.

CloudFormation reports all of these only at deploy time.
"""

import re
from collections.abc import Mapping
from typing import Any

from cfn_typed.constraints import _is_intrinsic, _number, _Resolver, _shown

_DEFAULT_ARG = 3


def _parameter(name: str, decl: Mapping[str, Any], out: list[str]) -> None:
    if "Default" not in decl:
        return
    default = decl["Default"]
    where = f"Parameters.{name}.Default"
    kind = decl.get("Type")
    if kind == "Number":
        number = _number(default)
        if number is None:
            out.append(f"{where}: {default!r} is not a number")
        else:
            if "MinValue" in decl and number < decl["MinValue"]:
                out.append(f"{where}: {default!r} is less than MinValue {decl['MinValue']}")
            if "MaxValue" in decl and number > decl["MaxValue"]:
                out.append(f"{where}: {default!r} is greater than MaxValue {decl['MaxValue']}")
    allowed = decl.get("AllowedValues")
    if isinstance(allowed, list) and str(default) not in {str(a) for a in allowed}:
        out.append(f"{where}: {default!r} is not one of the AllowedValues {_shown(allowed)}")
    if kind in ("String", "CommaDelimitedList") and isinstance(default, str):
        pattern = decl.get("AllowedPattern")
        if isinstance(pattern, str):
            try:
                if not re.fullmatch(pattern, default):
                    out.append(f"{where}: {default!r} does not match the AllowedPattern {pattern!r}")
            except re.error:
                pass  # written for another regex dialect: leave it unchecked rather than guess
        if kind == "String":
            if "MinLength" in decl and len(default) < decl["MinLength"]:
                out.append(f"{where}: {default!r} is shorter than MinLength {decl['MinLength']}")
            if "MaxLength" in decl and len(default) > decl["MaxLength"]:
                out.append(f"{where}: {default!r} is longer than MaxLength {decl['MaxLength']}")


class _Walker:
    def __init__(self, template: Mapping[str, Any], defaults: bool) -> None:
        self.mappings: Mapping[str, Any] = template.get("Mappings", {})
        self.resolver = _Resolver(template, defaults)
        self.problems: list[str] = []

    def _find_in_map(self, arg: list[Any], path: str) -> None:
        table = self.mappings.get(arg[0]) if isinstance(arg[0], str) else None
        if not isinstance(table, Mapping) or (len(arg) > 3 and isinstance(arg[3], Mapping) and "DefaultValue" in arg[3]):
            return
        for first, origin in self.resolver.candidates(arg[1]):
            note = f" ({origin})" if origin else ""
            if not isinstance(first, str):
                continue
            row = table.get(first)
            if not isinstance(row, Mapping):
                self.problems.append(f"{path}: Fn::FindInMap key {first!r} is not in mapping {arg[0]!r}, which has {_shown(list(table))}{note}")
                continue
            for second, origin2 in self.resolver.candidates(arg[2]):
                if isinstance(second, str) and second not in row:
                    note2 = f" ({origin2})" if origin2 else ""
                    self.problems.append(f"{path}: Fn::FindInMap key {second!r} is not in {arg[0]}/{first}, which has {_shown(list(row))}{note2}")

    def walk(self, node: Any, path: str) -> None:
        if isinstance(node, list):
            for i, item in enumerate(node):
                self.walk(item, f"{path}[{i}]")
            return
        if not isinstance(node, Mapping):
            return
        if len(node) == 1:
            (key, value), = node.items()
            if key == "Fn::FindInMap" and isinstance(value, list) and len(value) >= _DEFAULT_ARG:
                self._find_in_map(value, path)
            elif key == "Fn::Select" and isinstance(value, list) and len(value) == 2 and isinstance(value[1], list):
                index = value[0]
                index = int(index) if isinstance(index, str) and index.isdigit() else index
                if isinstance(index, int) and not isinstance(index, bool) and not _is_intrinsic(value[1]) and not 0 <= index < len(value[1]):
                    self.problems.append(f"{path}: Fn::Select index {index} is outside the list, which has {len(value[1])} items")
        for key, item in node.items():
            self.walk(item, f"{path}.{key}")


def find_value_problems(template: Mapping[str, Any], *, defaults: bool = True) -> list[str]:
    """Every bad `Fn::FindInMap` key, `Fn::Select` index and parameter default in `template`, one readable line each."""
    w = _Walker(template, defaults)
    for name, decl in template.get("Parameters", {}).items():
        if isinstance(decl, Mapping):
            _parameter(name, decl, w.problems)
    for section in ("Resources", "Outputs", "Conditions"):
        w.walk(template.get(section, {}), section)
    return list(dict.fromkeys(w.problems))
