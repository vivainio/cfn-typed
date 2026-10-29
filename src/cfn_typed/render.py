"""Render a template as JSON, or as readable YAML with CloudFormation's short-form intrinsics.

YAML needs PyYAML (`pip install cfn-typed[yaml]`); JSON needs nothing.
"""

import json
from collections.abc import Mapping
from typing import Any

# Intrinsics that have a short form. `Condition` is left out: as a lone key it is
# usually a resource attribute, not `!Condition`.
_SHORT = {"Ref"} | {
    f"Fn::{n}" for n in (
        "Base64", "Cidr", "FindInMap", "GetAtt", "GetAZs", "ImportValue", "Join", "Select", "Split", "Sub",
        "Transform", "And", "Equals", "If", "Not", "Or",
    )
}


def to_json(template: Mapping[str, Any], indent: int | None = 2) -> str:
    return json.dumps(template, indent=indent)


def _intrinsic(data: Any) -> tuple[str, Any] | None:
    if isinstance(data, dict) and len(data) == 1:
        (key, value), = data.items()
        if key in _SHORT:
            return key, value
    return None


def to_yaml(template: Mapping[str, Any]) -> str:
    """YAML in insertion order, indented lists, block scalars for multi-line text, `!Ref`/`!GetAtt`/`!Sub`..."""
    import yaml

    class Dumper(yaml.SafeDumper):
        def ignore_aliases(self, data: Any) -> bool:  # shared lists (e.g. tags) are repeated, not &anchored
            return True

        def increase_indent(self, flow: bool = False, indentless: bool = False) -> None:
            super().increase_indent(flow, False)  # "- " is indented under its key

        def choose_scalar_style(self) -> str:
            # PyYAML quotes every scalar with a custom tag; `!Ref Queue` reads better than `!Ref 'Queue'`
            event = self.event
            if isinstance(event, yaml.ScalarEvent) and event.tag and event.tag.startswith("!") and not event.style:
                if self.analysis is None:
                    self.analysis = self.analyze_scalar(event.value)
                a = self.analysis
                if not (self.simple_key_context and (a.empty or a.multiline)):
                    if (self.flow_level and a.allow_flow_plain) or (not self.flow_level and a.allow_block_plain):
                        return ""
            return super().choose_scalar_style()

    def represent_str(dumper: Any, data: str) -> Any:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|" if "\n" in data else None)

    def represent_dict(dumper: Any, data: dict[str, Any]) -> Any:
        hit = _intrinsic(data)
        if hit is None:
            return dumper.represent_mapping("tag:yaml.org,2002:map", data)
        key, value = hit
        if _intrinsic(value) is not None:  # AWS forbids short forms nested directly: keep the outer one long
            return dumper.represent_mapping("tag:yaml.org,2002:map", data)
        if key == "Fn::GetAtt" and isinstance(value, list) and len(value) == 2 and all(isinstance(v, str) for v in value):
            value = ".".join(value)
        node = dumper.represent_data(value)
        node.tag = "!" + key.removeprefix("Fn::")
        return node

    Dumper.add_representer(str, represent_str)
    Dumper.add_representer(dict, represent_dict)
    return yaml.dump(template, Dumper=Dumper, sort_keys=False, default_flow_style=False, width=200, allow_unicode=True)
