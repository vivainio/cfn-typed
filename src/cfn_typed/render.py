"""Render a template as JSON, or as readable YAML with CloudFormation's short-form intrinsics.

YAML uses ruamel.yaml, a regular dependency; it is what lets a value carry a comment (see `cfn_typed.comments`).
"""

import io
import json
import re
from collections.abc import Mapping
from typing import Any

from cfn_typed.comments import comment_of

# Intrinsics that have a short form. `Condition` is left out: as a lone key it is
# usually a resource attribute, not `!Condition`.
_SHORT = {"Ref"} | {
    f"Fn::{n}" for n in (
        "Base64", "Cidr", "FindInMap", "GetAtt", "GetAZs", "ImportValue", "Join", "Select", "Split", "Sub",
        "Transform", "And", "Equals", "If", "Not", "Or",
    )
}


def to_json(template: Mapping[str, Any], indent: int | str | None = 2) -> str:
    """JSON in insertion order. `indent` is as in `json.dumps`: a number of spaces, or a string such as `"\\t"`."""
    return json.dumps(template, indent=indent)


def _intrinsic(data: Any) -> tuple[str, Any] | None:
    if isinstance(data, dict) and len(data) == 1:
        (key, value), = data.items()
        if key in _SHORT:
            return key, value
    return None


class _Short:
    """A value written behind a short-form tag: `!Ref Queue`, `!Join [...]`."""

    def __init__(self, tag: str, value: Any) -> None:
        self.tag = tag
        self.value = value


# Strings that a YAML 1.1 reader (CloudFormation's) takes for something other than text, which ruamel's 1.2 would write bare.
_NOT_TEXT = re.compile(
    r"""^(?: y|Y|yes|Yes|YES|n|N|no|No|NO|true|True|TRUE|false|False|FALSE|on|On|ON|off|Off|OFF|null|Null|NULL|~|<<|=
    | [-+]?(?:\d[\d_]*|0x[0-9a-fA-F_]+|0b[01_]+|0o[0-7_]+)
    | [-+]?(?:\d[\d_]*\.[\d_]*|\.\d[\d_]*)(?:[eE][-+]?\d+)?
    | [-+]?\d[\d_]*[eE][-+]?\d+
    | [-+]?\.(?:inf|Inf|INF) | \.(?:nan|NaN|NAN)
    | \d+(?::[0-5]?\d)+(?:\.\d*)?
    | \d{4}-\d\d?-\d\d?(?:[Tt\s].*)?
    )$""",
    re.VERBOSE,
)


def to_yaml(template: Mapping[str, Any]) -> str:
    """YAML in insertion order, indented lists, block scalars for multi-line text, `!Ref`/`!GetAtt`/`!Sub`...

    A value marked with `value @ note("text")` gets a `# text` line above its key (or list item).
    """
    from ruamel.yaml import YAML
    from ruamel.yaml.comments import CommentedMap, CommentedSeq
    from ruamel.yaml.emitter import Emitter as BaseEmitter
    from ruamel.yaml.representer import RoundTripRepresenter
    from ruamel.yaml.scalarstring import LiteralScalarString, SingleQuotedScalarString

    class Representer(RoundTripRepresenter):
        def ignore_aliases(self, data: Any) -> bool:  # shared lists (e.g. tags) are repeated, not &anchored
            return True

    def represent_short(representer: Any, data: _Short) -> Any:
        node = representer.represent_data(data.value)
        node.tag = data.tag
        return node

    Representer.add_representer(_Short, represent_short)

    class Emitter(BaseEmitter):
        def choose_scalar_style(self) -> Any:
            style = super().choose_scalar_style()
            # ruamel double-quotes any string that holds a `'`; single quotes (`''` for a quote) read better
            if style == '"' and not self.event.style and "\n" not in self.event.value and self.analysis.allow_single_quoted:
                return "'"
            return style

    def quoted(value: str) -> str:
        """A key or a one-line value, quoted when a YAML 1.1 reader would not take it for text."""
        return SingleQuotedScalarString(value) if not value or _NOT_TEXT.match(value) else value  # `!GetAZs ''` must keep its quotes

    def text(value: str) -> str:
        return LiteralScalarString(value) if "\n" in value else quoted(value)

    def note(container: Any, key: Any, value: Any, col: int) -> None:
        lines = comment_of(value)
        if lines:
            container.yaml_set_comment_before_after_key(key, before="\n".join(lines), indent=col)

    # `col` is where the node's own lines start: the keys of a mapping, the dashes of a sequence. That is how far a
    # comment above one of them is indented.
    def build(data: Any, col: int) -> Any:
        if isinstance(data, dict):
            hit = _intrinsic(data)
            if hit is not None:
                key, value = hit
                if _intrinsic(value) is None:  # AWS forbids short forms nested directly: otherwise the outer one stays long
                    if key == "Fn::GetAtt" and isinstance(value, list) and len(value) == 2 and all(isinstance(v, str) for v in value):
                        value = ".".join(value)
                    return _Short("!" + key.removeprefix("Fn::"), build(value, col))
            mapping = CommentedMap()
            for key, value in data.items():
                mapping[quoted(key) if isinstance(key, str) else key] = build(value, col + 2)
                note(mapping, key, value, col)
            return mapping
        if isinstance(data, list):
            sequence = CommentedSeq()
            for i, value in enumerate(data):
                sequence.append(build(value, col + (4 if isinstance(value, list) else 2)))
                note(sequence, i, value, col)
            return sequence
        if isinstance(data, str):
            return text(str(data))
        if isinstance(data, bool) or data is None:
            return data
        if isinstance(data, int):
            return int(data)
        if isinstance(data, float):
            return float(data)
        return data

    yaml = YAML()
    yaml.Representer = Representer
    yaml.Emitter = Emitter
    yaml.indent(mapping=2, sequence=4, offset=2)  # "- " is indented under its key
    yaml.width = 200
    yaml.default_flow_style = False
    yaml.allow_unicode = True
    out = io.StringIO()
    yaml.dump(build(template, 0), out)
    return out.getvalue()
