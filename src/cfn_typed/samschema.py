"""AWS SAM's resource types (`AWS::Serverless::*`) as registry-style schemas, for `cfn-typegen`.

SAM publishes one JSON schema for a whole template (`samtranslator/schema/schema.json` in
aws/serverless-application-model). It is not shaped like the CloudFormation registry's one-file-per-type
schemas, so this module cuts it into the shape the generator already reads: for each SAM resource a
`{typeName, description, properties, required, definitions}` dict. The release tag is pinned (`sam = "v1.116.0"`
in `cfn-typegen.toml`) so a SAM release never changes generated code unasked.
"""

import copy
import json
import os
import re
import urllib.request
from pathlib import Path
from typing import Any

Schema = dict[str, Any]

SAM_URL = "https://raw.githubusercontent.com/aws/serverless-application-model/{tag}/samtranslator/schema/schema.json"
SAM_CACHE = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "cfn-typegen"

_RESOURCE = re.compile(r"samtranslator__internal__schema_source__aws_serverless_\w+?__Resource")
_PREFIX = re.compile(r"samtranslator__internal__schema_source__(aws_serverless_\w+?__)?")


def cache_path(tag: str) -> Path:
    return SAM_CACHE / f"sam-{tag}.json"


def ensure_sam(tag: str, refresh: bool = False, path: Path | None = None) -> Path:
    """The cached SAM schema for release `tag`, downloaded first if it is missing (or `refresh`)."""
    path = path or cache_path(tag)
    if refresh or not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        url = SAM_URL.format(tag=tag)
        print(f"downloading {url}")
        partial = path.with_name(path.name + ".part")  # a failed download must not clobber a good cache
        try:
            urllib.request.urlretrieve(url, partial)
            os.replace(partial, path)
        except BaseException:
            partial.unlink(missing_ok=True)
            raise
    return path


def _refs(node: Any) -> set[str]:
    """The definition names `node` refers to."""
    found: set[str] = set()
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/definitions/"):
            found.add(ref.removeprefix("#/definitions/"))
        for v in node.values():
            found |= _refs(v)
    elif isinstance(node, list):
        for v in node:
            found |= _refs(v)
    return found


def _reachable(defs: Schema, start: str) -> list[str]:
    seen: dict[str, None] = {}
    todo = [start]
    while todo:
        name = todo.pop()
        if name not in seen and name in defs:
            seen[name] = None
            todo += sorted(_refs(defs[name]))
    return list(seen)


def _rewrite(node: Any, names: dict[str, str]) -> Any:
    """A copy of `node` with `$ref`s renamed and SAM's `markdownDescription` offered as `description`."""
    if isinstance(node, dict):
        out = {k: _rewrite(v, names) for k, v in node.items()}
        parts = out.get("allOf")
        if isinstance(parts, list) and len(parts) == 1 and isinstance(parts[0], dict):  # pydantic's way of writing a ref with a description
            out = {**{k: v for k, v in out.items() if k != "allOf"}, **parts[0]}
        ref = out.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/definitions/"):
            out["$ref"] = "#/definitions/" + names.get(ref.removeprefix("#/definitions/"), ref.removeprefix("#/definitions/"))
        only = out.get("enum")
        if isinstance(only, list) and len(only) == 1 and isinstance(only[0], str):  # `Type: "SQS"`: a Literal lets the checker pick the event
            out["x-literal"] = only[0]
        if "description" not in out and isinstance(out.get("markdownDescription"), str):
            out["description"] = out["markdownDescription"]
        return out
    if isinstance(node, list):
        return [_rewrite(v, names) for v in node]
    return node


def sam_schemas(doc: Schema) -> list[Schema]:
    """One registry-style schema per `AWS::Serverless::*` resource in SAM's template schema `doc`."""
    defs: Schema = doc["definitions"]
    out = []
    for key in sorted(k for k in defs if _RESOURCE.fullmatch(k)):
        resource = defs[key]
        type_name = resource["properties"]["Type"]["enum"][0]
        ref = resource["properties"].get("Properties", {}).get("$ref", "")
        if not ref.startswith("#/definitions/") or ref.removeprefix("#/definitions/") not in defs:
            continue
        top = ref.removeprefix("#/definitions/")
        reachable = _reachable(defs, top)
        short = {k: _PREFIX.sub("", k) for k in reachable}
        counts = {n: list(short.values()).count(n) for n in short.values()}
        names = {k: (v if counts[v] == 1 else k) for k, v in short.items()}  # keep the long name on a clash
        body = _rewrite(copy.deepcopy(defs[top]), names)
        out.append({
            "typeName": type_name,
            "description": body.get("description") or resource.get("description") or "",
            "properties": body.get("properties", {}),
            "required": body.get("required", []),
            "additionalProperties": body.get("additionalProperties", False),
            "definitions": {names[k]: _rewrite(copy.deepcopy(defs[k]), names) for k in reachable if k != top},
        })
    return out


def load_sam(path: Path) -> list[Schema]:
    return sam_schemas(json.loads(path.read_text()))
