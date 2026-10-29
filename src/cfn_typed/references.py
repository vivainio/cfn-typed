"""Check that every name a template refers to exists, and that resources do not depend on each other in a circle.

A logical ID is a bare string wherever it is used, so `ref("Jbos")` renders fine and fails at deploy time. This walks
the finished template instead, which also covers fragments that were `combine`d from patterns:

    problems = find_reference_problems(template)   # [] when every reference resolves

Checked: `Ref`, `Fn::GetAtt`, `${Name}` and `${Name.Attr}` in `Fn::Sub`, `DependsOn`, `Condition` (on a resource or
an output, and `{"Condition": ...}` inside a condition), the condition name of `Fn::If`, and the map name of
`Fn::FindInMap`. Pseudo parameters (`AWS::Region`, ...) always resolve. Not checked: that a `GetAtt` attribute exists
on its resource type.
"""

import difflib
import re
from collections.abc import Mapping
from typing import Any

_SUB_VAR = re.compile(r"\$\{([^}]*)\}")


def _suggest(name: str, known: set[str]) -> str:
    close = difflib.get_close_matches(name, sorted(known), n=1)
    return f" (did you mean {close[0]!r}?)" if close else ""


class _Walker:
    def __init__(self, template: Mapping[str, Any]) -> None:
        self.resources: set[str] = set(template.get("Resources", {}))
        self.parameters: set[str] = set(template.get("Parameters", {}))
        self.conditions: set[str] = set(template.get("Conditions", {}))
        self.mappings: set[str] = set(template.get("Mappings", {}))
        self.problems: list[str] = []
        self.uses: set[str] = set()  # resources referred to inside the part being walked

    def _value(self, name: object, path: str, what: str) -> None:
        """A `Ref` or `${Name}`: a resource, a parameter or a pseudo parameter."""
        if not isinstance(name, str) or name.startswith("AWS::"):
            return
        if name in self.resources:
            self.uses.add(name)
        elif name not in self.parameters:
            known = self.resources | self.parameters
            self.problems.append(f"{path}: {what} refers to {name!r}, which is not a resource or parameter{_suggest(name, known)}")

    def _resource(self, name: object, path: str, what: str) -> None:
        if not isinstance(name, str):
            return
        if name in self.resources:
            self.uses.add(name)
        else:
            self.problems.append(f"{path}: {what} refers to {name!r}, which is not a resource{_suggest(name, self.resources)}")

    def _condition(self, name: object, path: str, what: str) -> None:
        if isinstance(name, str) and name not in self.conditions:
            self.problems.append(f"{path}: {what} refers to {name!r}, which is not a condition{_suggest(name, self.conditions)}")

    def _sub(self, value: Any, path: str) -> None:
        text, local = (value[0], value[1]) if isinstance(value, list) and len(value) == 2 else (value, {})
        if not isinstance(text, str):
            return
        local = local if isinstance(local, Mapping) else {}
        for var in _SUB_VAR.findall(text):
            if var.startswith("!") or var in local:
                continue
            self._value(var.split(".")[0], path, "Fn::Sub")

    def walk(self, node: Any, path: str) -> None:
        if isinstance(node, list):
            for i, item in enumerate(node):
                self.walk(item, f"{path}[{i}]")
            return
        if not isinstance(node, Mapping):
            return
        if len(node) == 1:
            (key, value), = node.items()
            if key == "Ref":
                self._value(value, path, "Ref")
            elif key == "Fn::GetAtt":
                logical = value.split(".")[0] if isinstance(value, str) else value[0] if isinstance(value, list) and value else None
                self._resource(logical, path, "Fn::GetAtt")
            elif key == "Fn::Sub":
                self._sub(value, path)
            elif key == "Fn::If" and isinstance(value, list) and value:
                self._condition(value[0], path, "Fn::If")
            elif key == "Fn::FindInMap" and isinstance(value, list) and value:
                if isinstance(value[0], str) and value[0] not in self.mappings:
                    self.problems.append(f"{path}: Fn::FindInMap refers to {value[0]!r}, which is not a mapping{_suggest(value[0], self.mappings)}")
            elif key == "Condition" and isinstance(value, str):  # a policy statement's Condition is a dict, never a string
                self._condition(value, path, "Condition")
        for key, value in node.items():
            self.walk(value, f"{path}.{key}")


def _cycle(graph: Mapping[str, set[str]]) -> list[str] | None:
    """One dependency cycle as `[A, B, A]`, or None."""
    done: set[str] = set()
    stack: list[str] = []

    def visit(name: str) -> list[str] | None:
        if name in stack:
            return stack[stack.index(name):] + [name]
        if name in done:
            return None
        stack.append(name)
        for dep in sorted(graph.get(name, ())):
            found = visit(dep)
            if found:
                return found
        stack.pop()
        done.add(name)
        return None

    for name in sorted(graph):
        found = visit(name)
        if found:
            return found
    return None


def find_reference_problems(template: Mapping[str, Any]) -> list[str]:
    """Every dangling reference and every dependency cycle in `template`, one readable line each."""
    w = _Walker(template)
    graph: dict[str, set[str]] = {}
    for logical, resource in template.get("Resources", {}).items():
        path = f"Resources.{logical}"
        w.uses = set()
        w.walk({k: v for k, v in resource.items() if k not in ("DependsOn", "Condition")}, path)
        depends = resource.get("DependsOn", [])
        for dep in [depends] if isinstance(depends, str) else depends:
            w._resource(dep, f"{path}.DependsOn", "DependsOn")
        if "Condition" in resource:
            w._condition(resource["Condition"], f"{path}.Condition", "Condition")
        graph[logical] = set(w.uses)
    for section in ("Conditions", "Outputs"):
        for name, body in template.get(section, {}).items():
            path = f"{section}.{name}"
            w.walk({k: v for k, v in body.items() if k != "Condition"} if section == "Outputs" else body, path)
            if section == "Outputs" and "Condition" in body:
                w._condition(body["Condition"], f"{path}.Condition", "Condition")
    cycle = _cycle(graph)
    if cycle:
        w.problems.append(f"Resources: circular dependency {' -> '.join(cycle)}")
    return w.problems
