"""Check a finished template against the value constraints in the registry schemas: allowed values, patterns, lengths,
number ranges and item counts.

    problems = find_constraint_problems(template, cfn_types)   # [] when every checked value is within its constraints

`cfn_types` is the package `cfn-typegen` generated. Each service module carries a `CONSTRAINTS` table for its resources,
and only the services the template uses are imported.

An intrinsic is followed as far as the template itself decides its value, and skipped beyond that. Followed:

- `Ref` to a parameter: each of its `AllowedValues`, else its `Default` (a default can be overridden at deploy time,
  and one that is only a placeholder behind an `Fn::If` is reported too; pass `defaults=False` to leave them out);
- `Fn::If`: both branches; `Fn::FindInMap`: the entry for literal keys, else every entry under the unknown key;
- `Fn::Sub`, `Fn::Join`, `Fn::Select` and `Fn::Split` whose pieces are all known by the rules above.

Not followed, because CloudFormation decides the value at deploy time: `Ref` to a resource or a pseudo parameter,
`Fn::GetAtt`, `Fn::ImportValue`, `Fn::GetAZs`, SSM-typed parameters and `{{resolve:...}}` references.

The registry's constraints are sometimes stricter than CloudFormation, as its `required` lists are. Generate with
`unconstrained = ["AWS::Service::Resource.Property"]` to drop one.
"""

import importlib
import itertools
import keyword
import re
from collections.abc import Mapping
from types import ModuleType
from typing import Any

# The CONSTRAINTS tables are written as small as possible, so their keys are one letter. A node is a dict of these
# plus `P` (property name -> node), `T` (the node every list item must satisfy) and `V` (the same for a map's values).
SHORT = {"enum": "e", "pattern": "p", "minLength": "l", "maxLength": "L", "minimum": "m", "maximum": "M", "minItems": "i", "maxItems": "I"}
PROPS, ITEMS, VALUES = "P", "T", "V"

_SUB_VAR = re.compile(r"\$\{([^}]*)\}")
_LIMIT = 64  # most combinations tried for one value, so a Sub with several mapped parts cannot explode
_DEPTH = 8

Candidates = list[tuple[Any, str]]  # a value the property may take, and where it came from ("" for a literal)


def _service_module(types: ModuleType, type_name: str) -> ModuleType | None:
    parts = type_name.split("::")
    if len(parts) < 3:
        return None
    service = parts[1].lower()
    name = f"{types.__name__}.{service}_" if keyword.iskeyword(service) else f"{types.__name__}.{service}"
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError as e:
        if e.name == name:
            return None  # that service was not generated, so there is nothing to check against
        raise


class _Tables:
    """The constraint table of each resource type, read from the generated package on first use."""

    def __init__(self, types: ModuleType | Mapping[str, Any]) -> None:
        self.types = types
        self.cache: dict[str, Mapping[str, Any]] = {}

    def get(self, type_name: object) -> Mapping[str, Any]:
        if not isinstance(type_name, str):
            return {}
        if isinstance(self.types, Mapping):
            return self.types.get(type_name, {})
        if type_name not in self.cache:
            module = _service_module(self.types, type_name)
            if module is not None and not hasattr(module, "CONSTRAINTS"):
                raise ValueError(f"{module.__name__} has no CONSTRAINTS: regenerate it without --no-constraints")
            self.cache[type_name] = getattr(module, "CONSTRAINTS", {}).get(type_name, {})
        return self.cache[type_name]


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):  # CloudFormation takes "443" for an integer
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _shown(values: list[Any], most: int = 8) -> str:
    return ", ".join(map(repr, values[:most])) + (", ..." if len(values) > most else "")


class _Resolver:
    """Possible values of an intrinsic, as far as the template itself determines them."""

    def __init__(self, template: Mapping[str, Any], defaults: bool) -> None:
        self.parameters: Mapping[str, Any] = template.get("Parameters", {})
        self.mappings: Mapping[str, Any] = template.get("Mappings", {})
        self.defaults = defaults

    def candidates(self, value: Any, depth: int = 0) -> Candidates:
        if not (isinstance(value, Mapping) and len(value) == 1) or depth > _DEPTH:
            return [(value, "")]
        (key, arg), = value.items()
        match key:
            case "Ref":
                return self.ref(arg)
            case "Fn::If" if isinstance(arg, list) and len(arg) == 3:
                out: Candidates = []
                for branch, label in ((arg[1], "true"), (arg[2], "false")):
                    out += [(v, o or f"Fn::If {label} branch") for v, o in self.candidates(branch, depth + 1)]
                return out
            case "Fn::FindInMap" if isinstance(arg, list) and len(arg) >= 3:
                return self.find_in_map(arg, depth)
            case "Fn::Sub":
                return self.sub(arg, depth)
            case "Fn::Join" if isinstance(arg, list) and len(arg) == 2 and isinstance(arg[0], str) and isinstance(arg[1], list):
                return [(arg[0].join(map(str, parts)), "Fn::Join") for parts in self.combos(arg[1], depth)]
            case "Fn::Select" if isinstance(arg, list) and len(arg) == 2:
                return self.select(arg, depth)
            case "Fn::Split" if isinstance(arg, list) and len(arg) == 2 and isinstance(arg[0], str):
                return [(str(v).split(arg[0]), "Fn::Split") for v, _ in self.candidates(arg[1], depth + 1)]
            case k if k == "Condition" or k.startswith("Fn::"):
                return []  # GetAtt, ImportValue, GetAZs, Base64, ...: decided at deploy time
        return [(value, "")]  # a map that merely has one key

    def ref(self, name: object) -> Candidates:
        param = self.parameters.get(name) if isinstance(name, str) else None
        if not isinstance(param, Mapping):
            return []  # a resource, a pseudo parameter such as AWS::NoValue, or nothing
        kind = str(param.get("Type", "String"))
        if kind.startswith(("AWS::SSM::Parameter::Value", "List<")) or kind == "CommaDelimitedList":
            return []  # an SSM parameter's Default is a path, not the value; list parameters are not followed
        if param.get("AllowedValues"):
            return [(v, f"Ref {name}, allowed value") for v in param["AllowedValues"]]
        if self.defaults and "Default" in param:
            return [(param["Default"], f"Ref {name}, default")]
        return []

    def combos(self, parts: list[Any], depth: int) -> list[list[Any]]:
        """Every combination of the parts' possible values; empty when any part is unknown."""
        options = [[v for v, _ in self.candidates(p, depth + 1)] for p in parts]
        if not all(options):
            return []
        out = []
        for combo in itertools.islice(itertools.product(*options), _LIMIT):
            out.append(list(combo))
        return out

    def sub(self, arg: Any, depth: int) -> Candidates:
        text, local = (arg[0], arg[1]) if isinstance(arg, list) and len(arg) == 2 else (arg, {})
        if not isinstance(text, str) or not isinstance(local, Mapping):
            return []
        names = list(dict.fromkeys(v for v in _SUB_VAR.findall(text) if not v.startswith("!")))
        parts = [local[n] if n in local else {"Ref": n} for n in names]
        out: Candidates = []
        for combo in self.combos(parts, depth) if names else [[]]:
            filled = dict(zip(names, combo))
            out.append((_SUB_VAR.sub(lambda m: m.group(0).replace("${!", "${") if m.group(1).startswith("!") else str(filled[m.group(1)]), text), "Fn::Sub"))
        return out

    def find_in_map(self, arg: list[Any], depth: int) -> Candidates:
        table = self.mappings.get(arg[0]) if isinstance(arg[0], str) else None
        if not isinstance(table, Mapping):
            return []
        first = [v for v, _ in self.candidates(arg[1], depth + 1)] or list(table)  # an unknown key: any entry may be used
        out: Candidates = []
        for k1 in first:
            row = table.get(k1) if isinstance(k1, str) else None
            if not isinstance(row, Mapping):
                continue
            second = [v for v, _ in self.candidates(arg[2], depth + 1)] or list(row)
            out += [(row[k2], f"Fn::FindInMap {arg[0]}/{k1}/{k2}") for k2 in second if isinstance(k2, str) and k2 in row]
        return out

    def select(self, arg: list[Any], depth: int) -> Candidates:
        out: Candidates = []
        for items, _ in self.candidates(arg[1], depth + 1):
            if not isinstance(items, list):
                continue
            indexes = [_number(v) for v, _ in self.candidates(arg[0], depth + 1)] or range(len(items))
            out += [(items[int(i)], "Fn::Select") for i in indexes if i is not None and 0 <= int(i) < len(items)]
        return out


def _is_intrinsic(value: Any) -> bool:
    if not (isinstance(value, Mapping) and len(value) == 1):
        return False
    key = next(iter(value))
    return key in ("Ref", "Condition") or key.startswith("Fn::")


def _check(value: Any, node: Mapping[str, Any], path: str, out: list[str], resolver: _Resolver, origin: str = "") -> None:
    if _is_intrinsic(value):
        for known, where in resolver.candidates(value):
            _check(known, node, path, out, resolver, where)
        return
    if isinstance(value, str) and value.startswith("{{resolve:"):
        return
    note = f" ({origin})" if origin else ""

    def report(message: str) -> None:
        out.append(f"{path}: {message}{note}")

    enum = node.get("e")
    if enum is not None and isinstance(value, (str, int, float)) and value not in enum and str(value) not in {str(e) for e in enum}:
        report(f"{value!r} is not one of {_shown(enum)}")
    if isinstance(value, str):
        if "l" in node and len(value) < node["l"]:
            report(f"{value!r} is shorter than the minimum length {node['l']}")
        if "L" in node and len(value) > node["L"]:
            report(f"{value!r} is longer than the maximum length {node['L']}")
        if "p" in node and not re.search(node["p"], value):
            report(f"{value!r} does not match the pattern {node['p']!r}")
    number = _number(value) if ("m" in node or "M" in node) and not isinstance(value, (list, Mapping)) else None
    if number is not None:
        if "m" in node and number < node["m"]:
            report(f"{value!r} is less than the minimum of {node['m']}")
        if "M" in node and number > node["M"]:
            report(f"{value!r} is greater than the maximum of {node['M']}")
    if isinstance(value, list):
        if "i" in node and len(value) < node["i"]:
            report(f"has {len(value)} items, fewer than the minimum of {node['i']}")
        if "I" in node and len(value) > node["I"]:
            report(f"has {len(value)} items, more than the maximum of {node['I']}")
        if "T" in node:
            for i, item in enumerate(value):
                _check(item, node["T"], f"{path}[{i}]", out, resolver, origin)
    elif isinstance(value, Mapping):
        for name, sub in node.get("P", {}).items():
            if name in value:
                _check(value[name], sub, f"{path}.{name}", out, resolver, origin)
        if "V" in node:
            for name, item in value.items():
                _check(item, node["V"], f"{path}.{name}", out, resolver, origin)


def find_constraint_problems(template: Mapping[str, Any], types: ModuleType | Mapping[str, Any], *, defaults: bool = True) -> list[str]:
    """Every property value in `template` that breaks a registry constraint, one readable line each.

    `types` is the generated package, or a hand-made `{type name: constraint table}` mapping.
    """
    tables, resolver = _Tables(types), _Resolver(template, defaults)
    problems: list[str] = []
    for logical, resource in template.get("Resources", {}).items():
        props = resource.get("Properties")
        table = tables.get(resource.get("Type"))
        if table and isinstance(props, Mapping):
            _check(props, {"P": table}, f"Resources.{logical}.Properties", problems, resolver)
    return problems
