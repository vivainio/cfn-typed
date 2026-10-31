"""`cfn-typed import`: turn an existing CloudFormation template into typed Python.

    sls package                                        # or: aws cloudformation get-template
    cfn-typegen --out cfn_types --template .serverless/cloudformation-template-update-stack.json
    cfn-typed import .serverless/cloudformation-template-update-stack.json -o stack.py

The result is a `build()` function whose resources are calls to the generated factories and whose intrinsics are the
builders of `cfn_typed`, so it renders to the same template and `ty` checks it. Nothing is guessed: logical ids,
property values and ordering are kept, which is what makes a change set against the existing stack empty.

What stays a plain dict, with a comment saying why: a resource whose type has no factory (`Custom::*`), a resource with
a key the factories do not take (`CreationPolicy`, `UpdatePolicy`), a property name that is not an identifier, and an
intrinsic in a shape the builders do not take.
"""

import json
import keyword
import re
from collections.abc import Mapping, Sequence
from typing import Any

from cfn_typed.typegen import pascal, reserved, snake

_RESOURCE_KEYS = {
    "Type": None,
    "Properties": None,
    "DependsOn": "depends_on",
    "DeletionPolicy": "deletion_policy",
    "UpdateReplacePolicy": "update_replace_policy",
    "Condition": "condition",
    "Metadata": "metadata",
}
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


def module_and_factory(type_name: str) -> tuple[str, str] | None:
    """Where the generated code puts a resource type: `AWS::Lambda::Function` is `lambda_.function`."""
    parts = type_name.split("::")
    if len(parts) < 3 or parts[0] == "Custom":
        return None
    service = parts[1].lower()
    name = snake(pascal("".join(parts[2:])))
    return (service + "_" if keyword.iskeyword(service) else service), (name + "_" if reserved(name) else name)


def _q(text: str) -> str:
    """A string literal in the repo's style (double quotes); JSON escapes are valid Python."""
    return json.dumps(text, ensure_ascii=False)


class _Writer:
    def __init__(self) -> None:
        self.modules: set[str] = set()
        self.notes: list[str] = []

    def lit(self, value: Any, level: int) -> str:
        """Python source for a template value, at indent `level`."""
        pad, inner = "    " * level, "    " * (level + 1)
        if isinstance(value, Mapping):
            if (call := self.intrinsic(value, level)) is not None:
                return call
            if not value:
                return "{}"
            items = [f"{inner}{_q(k)}: {self.lit(v, level + 1)}," for k, v in value.items()]
            return "{\n" + "\n".join(items) + f"\n{pad}}}"
        if isinstance(value, list):
            if not value:
                return "[]"
            if all(not isinstance(v, (Mapping, list)) for v in value) and len(repr(value)) < 80:
                return "[" + ", ".join(self.lit(v, level) for v in value) + "]"
            items = [f"{inner}{self.lit(v, level + 1)}," for v in value]
            return "[\n" + "\n".join(items) + f"\n{pad}]"
        return _q(value) if isinstance(value, str) else repr(value)

    def intrinsic(self, value: Mapping[str, Any], level: int) -> str | None:
        """A builder call for a one-key intrinsic, or None to leave the dict as it is."""
        if len(value) != 1:
            return None
        (key, arg), = value.items()
        def a(v: Any) -> str:
            return self.lit(v, level)

        call: str | None = None
        match key, arg:
            case "Ref", str():
                call = f"cfn.ref({_q(arg)})"
            case "Condition", str():
                call = f"cfn.condition_ref({_q(arg)})"
            case "Fn::GetAtt", [str() as logical, str() | Mapping() as attr]:
                call = f"cfn.get_att({_q(logical)}, {a(attr)})"
            case "Fn::GetAtt", str() if "." in arg:
                logical, attr = arg.split(".", 1)
                call = f"cfn.get_att({_q(logical)}, {_q(attr)})"
            case "Fn::Sub", str():
                call = f"cfn.sub({_q(arg)})"
            case "Fn::Sub", [str() as text, Mapping() as variables]:
                call = f"cfn.sub({_q(text)}, {a(variables)})"
            case "Fn::Join", [str() as sep, parts]:
                call = f"cfn.join({_q(sep)}, {a(parts)})"
            case "Fn::Select", [index, items]:
                call = f"cfn.select({a(index)}, {a(items)})"
            case "Fn::Split", [str() as delimiter, source]:
                call = f"cfn.split({_q(delimiter)}, {a(source)})"
            case "Fn::If", [str() as condition, if_true, if_false]:
                call = f"cfn.if_({_q(condition)}, {a(if_true)}, {a(if_false)})"
            case "Fn::FindInMap", [str() as map_name, top, second]:
                call = f"cfn.find_in_map({_q(map_name)}, {a(top)}, {a(second)})"
            case "Fn::ImportValue", _:
                call = f"cfn.import_value({a(arg)})"
            case "Fn::GetAZs", _:
                call = f"cfn.get_azs({a(arg)})"
            case "Fn::Base64", _:
                call = f"cfn.base64({a(arg)})"
            case "Fn::Cidr", [block, count, bits]:
                call = f"cfn.cidr({a(block)}, {a(count)}, {a(bits)})"
            case "Fn::Equals", [left, right]:
                call = f"cfn.equals({a(left)}, {a(right)})"
            case "Fn::And", list():
                call = f"cfn.and_({', '.join(a(v) for v in arg)})"
            case "Fn::Or", list():
                call = f"cfn.or_({', '.join(a(v) for v in arg)})"
            case "Fn::Not", [single]:
                call = f"cfn.not_({a(single)})"
        return call

    def resource(self, logical: str, res: Mapping[str, Any], level: int) -> str:
        pad = "    " * level
        key = f"{pad}{_q(logical)}: "
        type_name = res.get("Type", "")
        target = module_and_factory(type_name) if isinstance(type_name, str) else None
        extra = sorted(set(res) - set(_RESOURCE_KEYS))
        props = res.get("Properties", {})
        bad = [k for k in props if not _IDENT.fullmatch(k) or keyword.iskeyword(k)] if isinstance(props, Mapping) else ["Properties"]
        reason = (
            "no generated factory for this type" if target is None
            else f"keys the factories do not take: {', '.join(extra)}" if extra
            else f"property names that are not identifiers: {', '.join(bad)}" if bad
            else None
        )
        if reason or target is None:
            self.notes.append(f"{logical}: kept as a dict ({reason})")
            return f"{pad}# kept as a dict: {reason}\n{key}{self.lit(dict(res), level)},"
        module, factory = target
        self.modules.add(module)
        inner = "    " * (level + 1)
        args = [f"{inner}{name}={self.lit(res[k], level + 1)}," for k, name in _RESOURCE_KEYS.items() if name and k in res]
        args += [f"{inner}{k}={self.lit(v, level + 1)}," for k, v in props.items()]
        if not args:
            return f"{key}{module}.{factory}(),"
        return f"{key}{module}.{factory}(\n" + "\n".join(args) + f"\n{pad}),"


def _subbed(value: Any) -> Any:
    """`value` with every string that has a `${` wrapped in `Fn::Sub`, so that an object parsed out of a `Fn::Sub` string still substitutes."""
    if isinstance(value, str):
        return {"Fn::Sub": value} if "${" in value else value
    if isinstance(value, list):
        return [_subbed(v) for v in value]
    if isinstance(value, Mapping):
        return {k: _subbed(v) for k, v in value.items()}
    return value


def structure_definitions(template: Mapping[str, Any]) -> dict[str, Any]:
    """A copy of `template` where each state machine's `DefinitionString` (a JSON string, or `Fn::Sub` of one) is the parsed `Definition` object, which `cfn_typed.asl` types and checks. A string that is not JSON, or a `Fn::Sub` with variables, is left alone."""
    out = dict(template)
    resources = dict(template.get("Resources", {}))
    for logical, res in resources.items():
        props = res.get("Properties") if isinstance(res, Mapping) else None
        if not isinstance(props, Mapping) or res.get("Type") != "AWS::StepFunctions::StateMachine" or "Definition" in props:
            continue
        text, wrapped = props.get("DefinitionString"), False
        if isinstance(text, Mapping) and len(text) == 1 and isinstance(text.get("Fn::Sub"), str):
            text, wrapped = text["Fn::Sub"], True
        if not isinstance(text, str):
            continue
        try:
            parsed = json.loads(text)
        except ValueError:
            continue
        if isinstance(parsed, dict):
            new = {k: v for k, v in props.items() if k != "DefinitionString"}
            new["Definition"] = _subbed(parsed) if wrapped else parsed
            resources[logical] = {**res, "Properties": new}
    out["Resources"] = resources
    return out


_SECTIONS = ("AWSTemplateFormatVersion", "Description", "Transform", "Metadata", "Parameters", "Rules", "Mappings", "Conditions", "Resources", "Outputs")


def to_python(template: Mapping[str, Any], types: str = "cfn_types", *, definitions: bool = False) -> str:
    """Python source of a module with `build() -> cfn.Template`, for `template`. `types` is the package `cfn-typegen` wrote. `definitions=True` writes each state machine's definition as an object (see `structure_definitions`), so the module no longer renders to exactly `template`."""
    if definitions:
        template = structure_definitions(template)
    w = _Writer()
    body: list[str] = []
    for section in (*_SECTIONS, *sorted(set(template) - set(_SECTIONS))):
        if section not in template:
            continue
        value = template[section]
        if section == "Resources" and isinstance(value, Mapping):
            items = [w.resource(logical, res, 3) for logical, res in value.items()]
            body.append('        "Resources": {\n' + "\n".join(items) + "\n        },")
        else:
            body.append(f"        {_q(section)}: {w.lit(value, 2)},")
    head = ["import cfn_typed as cfn"]
    if w.modules:
        head.append(f"from {types} import {', '.join(sorted(w.modules))}")
    notes = [f"#   {n}" for n in w.notes]
    return "\n".join(
        [
            "# Imported by `cfn-typed import`. Check it with `cfn-typed emit`, and compare it with the original template.",
            *(["# Left as plain dicts:", *notes] if notes else []),
            "",
            *head,
            "",
            "",
            "def build() -> cfn.Template:",
            "    return {",
            *body,
            "    }",
            "",
        ]
    )


def main(path: str, out: str | None, types: str, definitions: bool = False) -> int:
    """The `import` subcommand: write the module to `out`, or print it."""
    import sys
    from pathlib import Path

    from cfn_typed.cli import load_template

    source = to_python(load_template(Path(path)), types, definitions=definitions)
    if out:
        Path(out).write_text(source)
        print(f"wrote {out}", file=sys.stderr)
    else:
        print(source, end="")
    return 0


__all__: Sequence[str] = ["main", "module_and_factory", "structure_definitions", "to_python"]
