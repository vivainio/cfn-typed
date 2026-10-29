"""Render a reference page per resource type from the CloudFormation schemas.

Run by scripts/build-docs.sh (and CI) before `zensical build`; the output in
docs/reference/ is gitignored, so the pages always match the schemas just downloaded.
"""

import re
from pathlib import Path
from typing import Any

from cfn_typed import typegen

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "reference"


def cell(text: str | None) -> str:
    return (text or "").replace("|", "\\|").replace("\n", " ").strip()


def describe(node: dict[str, Any], schema: dict[str, Any], depth: int = 0) -> str:
    if "$ref" in node and depth < 5:
        target: Any = schema
        for part in node["$ref"].removeprefix("#/").split("/"):
            target = target[part]
        name = node["$ref"].rsplit("/", 1)[-1]
        return f"{name} (object)" if target.get("properties") else describe(target, schema, depth + 1)
    t = node.get("type")
    if isinstance(t, list):
        return " or ".join(describe({**node, "type": x}, schema, depth) for x in t)
    if t == "array":
        item = node.get("items")
        return f"list of {describe(item, schema, depth + 1)}" if isinstance(item, dict) else "list"
    if t == "object":
        return "object" if node.get("properties") else "map"
    if t == "string" and node.get("enum"):
        return "string (one of a fixed set)"
    return t or "any"


def render(schema: dict[str, Any]) -> str:
    type_name = schema["typeName"]
    parts = type_name.split("::")
    res = typegen.pascal("".join(parts[2:]))
    svc = parts[1].lower() + ("_" if parts[1].lower() in typegen.keyword.kwlist else "")
    factory = typegen.snake(res) + ("_" if typegen.reserved(typegen.snake(res)) else "")
    hidden = typegen.readonly_props(schema)
    required = set(schema.get("required", ())) - hidden
    rows = [
        f"| `{k}` | {cell(describe(v, schema))} | {'yes' if k in required else ''} | {cell(typegen.short(v.get('description')))} |"
        for k, v in schema.get("properties", {}).items() if k not in hidden
    ]
    attrs = sorted(hidden)
    lines = [
        f"# {type_name}",
        "",
        cell(typegen.short(schema.get("description"))),
        "",
        "```python",
        f"from cfn_types import {svc}",
        "",
        f"{svc}.{factory}(**props)   # returns {svc}.{res}",
        "```",
        "",
        "## Properties",
        "",
        "| Property | Type | Required | Description |",
        "|---|---|---|---|",
        *rows,
        "",
    ]
    if attrs:
        lines += [
            "## Attributes",
            "",
            "Read-only values you can read with `get_att(logical_id, attribute)`. They are not accepted as inputs.",
            "",
            *[f"- `{a}`" for a in attrs],
            "",
        ]
    if url := schema.get("documentationUrl"):
        lines += [f"[AWS documentation]({url})", ""]
    return "\n".join(lines)


def main() -> None:
    wanted = [t for t in (ROOT / "examples" / "types.txt").read_text().split("\n") if t and not t.startswith("#")]
    schemas = typegen.select(typegen.load_schemas(typegen.ensure_schemas(typegen.CACHE)), wanted)
    OUT.mkdir(parents=True, exist_ok=True)
    index = ["# Reference", "", "Generated from the CloudFormation registry schemas when the book is built.", ""]
    for schema in schemas:
        slug = re.sub(r"\W+", "-", schema["typeName"].replace("AWS::", "")).lower()
        (OUT / f"{slug}.md").write_text(render(schema))
        index.append(f"- [{schema['typeName']}]({slug}.md)")
    (OUT / "index.md").write_text("\n".join(index) + "\n")
    print(f"wrote {len(schemas)} reference pages to {OUT}")


if __name__ == "__main__":
    main()
