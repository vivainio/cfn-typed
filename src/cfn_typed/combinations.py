"""Check which properties a template sets together: "exactly one of X or Y", "at least one of", "A needs B".

    problems = find_combination_problems(template, cfn_types)   # [] when every combination is allowed

`cfn_types` is the package `cfn-typegen` generated. Each service module carries a `RULES` table read from the registry
schemas' `oneOf`, `anyOf`, `dependencies` and `allOf`. Only the plain "these properties must be set" shape is kept; a
`oneOf` of types or of whole schemas is the type checker's job. CloudFormation reports a wrong combination only at deploy time.

Whether a property is set is read from the template. `{"Ref": "AWS::NoValue"}` is not set. An `Fn::If` with `AWS::NoValue` in
one branch may be set, and a rule is only reported when it is broken however that turns out. An `Fn::If` that picks between
whole objects is checked branch by branch. Not followed: `Ref` to a parameter or resource, and `Fn::GetAtt`, which are always set.
"""

from collections.abc import Iterator, Mapping
from types import ModuleType
from typing import Any

from cfn_typed.attributes import _Tables
from cfn_typed.constraints import _is_intrinsic

_NO_VALUE = {"Ref": "AWS::NoValue"}
_DEPTH = 8


def _branches(value: Any) -> list[Any] | None:
    if isinstance(value, Mapping) and len(value) == 1 and isinstance(value.get("Fn::If"), list) and len(value["Fn::If"]) == 3:
        return value["Fn::If"][1:]
    return None


def _state(value: Any, depth: int = 0) -> str:
    """"yes", "no" or "maybe": whether a property with this value is set."""
    if value == _NO_VALUE:
        return "no"
    if (branches := _branches(value)) and depth < _DEPTH:
        states = {_state(b, depth + 1) for b in branches}
        return states.pop() if len(states) == 1 else "maybe"
    return "yes"


def _objects(value: Any, segments: list[str], path: str, depth: int = 0) -> Iterator[tuple[Mapping[str, Any], str]]:
    """The objects `segments` leads to from `value`, following both branches of an `Fn::If`."""
    if (branches := _branches(value)) and depth < _DEPTH:
        for branch in branches:
            yield from _objects(branch, segments, path, depth + 1)
        return
    if not segments:
        if isinstance(value, Mapping) and not _is_intrinsic(value):
            yield value, path
        return
    head, rest = segments[0], segments[1:]
    if head == "[]" and isinstance(value, list):
        for i, item in enumerate(value):
            yield from _objects(item, rest, f"{path}[{i}]", depth)
    elif head == "*" and isinstance(value, Mapping) and not _is_intrinsic(value):
        for key, item in value.items():
            yield from _objects(item, rest, f"{path}.{key}", depth)
    elif isinstance(value, Mapping) and head in value:
        yield from _objects(value[head], rest, f"{path}.{head}", depth)


def _all(states: list[str]) -> str:
    return "no" if "no" in states else "yes" if all(s == "yes" for s in states) else "maybe"


def _names(branch: list[str]) -> str:
    return " + ".join(map(repr, branch))


def _check(obj: Mapping[str, Any], kind: str, data: Any, path: str, out: list[str]) -> None:
    def state(name: str) -> str:
        return _state(obj[name]) if name in obj else "no"

    if kind == "d":
        for name, needs in data.items():
            if state(name) == "yes":
                for need in needs:
                    if state(need) == "no":
                        out.append(f"{path}: {name!r} is set, which needs {need!r}")
        return
    states = [_all([state(n) for n in branch]) for branch in data]
    sure, possible = states.count("yes"), states.count("yes") + states.count("maybe")
    options = " or ".join(_names(b) for b in data)
    if possible == 0:
        out.append(f"{path}: {'exactly one' if kind == 'o' else 'at least one'} of {options} must be set, but none is")
    elif kind == "o" and sure > 1:
        out.append(f"{path}: exactly one of {options} must be set, but {sure} are")


def find_combination_problems(template: Mapping[str, Any], types: ModuleType | Mapping[str, Any]) -> list[str]:
    """Every property combination in `template` that a registry schema rules out, one readable line each.

    `types` is the generated package, or a hand-made `{type name: [[path, kind, data], ...]}` mapping: `path` is the
    property names down to an object (`"[]"` for list items, `"*"` for map values) and `kind` is `o` (exactly one of the
    branches, each a list of names that must all be set), `a` (at least one) or `d` (`{name: names it needs}`).
    """
    tables = _Tables(types, "RULES")
    out: list[str] = []
    for logical, resource in template.get("Resources", {}).items():
        for path, kind, data in tables.get(resource.get("Type")) or []:
            for obj, where in _objects(resource.get("Properties", {}), path, f"Resources.{logical}.Properties"):
                _check(obj, kind, data, where, out)
    return list(dict.fromkeys(out))
