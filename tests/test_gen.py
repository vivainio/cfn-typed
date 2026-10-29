from typing import Any

import pytest

from cfn_typed import typegen as gen

WIDGET: dict[str, Any] = {
    "typeName": "AWS::Foo::Widget",
    "definitions": {
        "Part": {"type": "object", "properties": {"N": {"type": "integer"}}, "required": ["N"]},
        "Node": {"type": "object", "properties": {"Next": {"$ref": "#/definitions/Node"}}},
        "Tag": {"type": "object", "properties": {"Key": {"type": "string"}, "Value": {"type": "string"}}},
    },
    "properties": {
        "Id": {"type": "string"},
        "Name": {"type": "string"},
        "Part": {"$ref": "#/definitions/Part"},
        "Node": {"$ref": "#/definitions/Node"},
        "Names": {"type": "array", "items": {"type": "string"}},
        "Labels": {"type": "object", "patternProperties": {".*": {"type": "string"}}},
        "Tags": {"type": "array", "items": {"$ref": "#/definitions/Tag"}},
    },
    "required": ["Name"],
    "readOnlyProperties": ["/properties/Id"],
}


def load() -> dict[str, Any]:
    ns: dict[str, Any] = {}
    exec(compile(gen.render_module("AWS::Foo", [WIDGET]), "<widget>", "exec"), ns)
    return ns


def test_generated_module_builds_resources() -> None:
    ns = load()
    part = ns["WidgetPart"](N=1)
    assert ns["widget"](Name="w", Part=part, depends_on="Other") == {
        "Type": "AWS::Foo::Widget",
        "Properties": {"Name": "w", "Part": {"N": 1}},
        "DependsOn": "Other",
    }


def test_read_only_properties_are_excluded_and_recursion_terminates() -> None:
    ns = load()
    assert "Id" not in ns["WidgetProps"].__annotations__
    assert "Next" in ns["WidgetNode"].__annotations__
    assert "WidgetTag" not in ns  # shared Tag type is reused


def test_imports_are_compact_and_only_what_is_used() -> None:
    src = gen.render_module("AWS::Foo", [WIDGET], docs=False)
    header = src.split("\n\n\n")[0]
    assert "from typing import" in header and "from cfn_typed.base import" in header
    assert " as _" not in header  # plain names, no aliases
    assert "Unpack" in header and "Literal" in header
    assert "Mapping" in header  # the Labels map uses it
    plain = gen.render_module("AWS::Foo", [{"typeName": "AWS::Foo::Bar", "properties": {"N": {"type": "integer"}}}], docs=False)
    assert "Mapping" not in plain.split("\n\n\n")[0]


def test_definitions_cannot_shadow_imported_names() -> None:
    schema = {"typeName": "AWS::Foo::Build", "properties": {"X": {"type": "string"}}}
    ns: dict[str, Any] = {}
    exec(compile(gen.render_module("AWS::Foo", [schema]), "<build>", "exec"), ns)
    assert ns["build2"](X="v") == {"Type": "AWS::Foo::Build", "Properties": {"X": "v"}}  # `build` stays the helper


def test_no_docs_drops_docstrings_but_not_types() -> None:
    schema = {**WIDGET, "description": "A widget.", "properties": {
        **WIDGET["properties"], "Name": {"type": "string", "description": "The name."}}}
    with_docs = gen.render_module("AWS::Foo", [schema])
    without = gen.render_module("AWS::Foo", [schema], docs=False)
    assert "The name." in with_docs and "A widget." in with_docs
    assert "The name." not in without and "A widget." not in without
    assert len(without) < len(with_docs)
    ns: dict[str, Any] = {}
    exec(compile(without, "<widget>", "exec"), ns)
    assert ns["widget"](Name="w") == {"Type": "AWS::Foo::Widget", "Properties": {"Name": "w"}}


def test_generated_files_opt_out_of_formatters_and_linters() -> None:
    lines = gen.render_module("AWS::Foo", [WIDGET]).splitlines()
    assert lines[0].startswith(gen.MARKER)  # `cfn-typegen` recognises its own files by this line
    assert lines[1:3] == ["# fmt: off", "# ruff: noqa"]


SEARCH_SET: list[dict[str, Any]] = [
    {"typeName": "AWS::ElasticLoadBalancingV2::LoadBalancer", "description": "An application or network load balancer."},
    {"typeName": "AWS::ElasticLoadBalancingV2::Listener", "description": "Listens on a port of a load balancer."},
    {"typeName": "AWS::ElasticLoadBalancing::LoadBalancer", "description": "A classic load balancer."},
    {"typeName": "AWS::Route53::RecordSet", "description": "Can point at a load balancer."},
    {"typeName": "AWS::SQS::Queue", "description": "A queue."},
]


def names(found: list[dict[str, Any]]) -> list[str]:
    return [s["typeName"] for s in found]


def test_search_requires_every_word_and_ignores_case() -> None:
    assert "AWS::SQS::Queue" not in names(gen.search(SEARCH_SET, ["LOAD", "balancer"]))
    assert names(gen.search(SEARCH_SET, ["queue"])) == ["AWS::SQS::Queue"]
    assert gen.search(SEARCH_SET, ["load", "nonsense"]) == []


def test_search_ranks_resource_name_then_type_name_then_description() -> None:
    assert names(gen.search(SEARCH_SET, ["loadbalancer"])) == [
        "AWS::ElasticLoadBalancing::LoadBalancer",    # in the resource name, shorter first
        "AWS::ElasticLoadBalancingV2::LoadBalancer",
    ]
    found = names(gen.search(SEARCH_SET, ["load", "balancer"]))
    assert found[:2] == ["AWS::ElasticLoadBalancing::LoadBalancer", "AWS::ElasticLoadBalancingV2::LoadBalancer"]
    # "balancer" is not in "ElasticLoadBalancing", so these two match through their descriptions only
    assert found[2:] == ["AWS::Route53::RecordSet", "AWS::ElasticLoadBalancingV2::Listener"]


def test_search_hides_descriptions_that_only_repeat_the_name() -> None:
    assert gen._BOILERPLATE.fullmatch("Resource Type definition for AWS::Foo::Bar")
    assert gen._BOILERPLATE.fullmatch("Resource schema for AWS::Foo::Bar.")
    assert not gen._BOILERPLATE.fullmatch("Resource Type definition for AWS::Foo::Bar, which does more")


def test_search_command_prints_names(capsys: Any, tmp_path: Any) -> None:
    import json
    import zipfile

    zip_path = tmp_path / "schemas.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        for i, schema in enumerate(SEARCH_SET):
            zf.writestr(f"{i}.json", json.dumps(schema))
    gen.main(["search", "queue", "--schemas", str(zip_path)])
    captured = capsys.readouterr()
    assert captured.out.startswith("AWS::SQS::Queue") and "A queue." in captured.out
    assert "1 match" in captured.err


def test_header_records_which_schema_snapshot_generated_the_file(tmp_path: Any) -> None:
    import hashlib
    import json
    import zipfile

    assert "Schema snapshot" not in gen.render_module("AWS::Foo", [WIDGET])  # only when a stamp is given
    zip_path = tmp_path / "schemas.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("w.json", json.dumps(WIDGET))
    stamp = gen.schema_stamp(zip_path)
    assert stamp == "sha256:" + hashlib.sha256(zip_path.read_bytes()).hexdigest()[:12]
    out = tmp_path / "types"
    gen.main(["--out", str(out), "--schemas", str(zip_path), "AWS::Foo::Widget"])
    header = (out / "foo.py").read_text().splitlines()
    assert header[0].startswith(gen.MARKER) and f"# Schema snapshot: {stamp}" in header[:6]


def test_refresh_redownloads_only_when_asked_and_keeps_the_cache_on_failure(tmp_path: Any, monkeypatch: Any) -> None:
    import zipfile

    source = tmp_path / "source.zip"
    cache = tmp_path / "cache" / "schemas.zip"

    def publish(content: str) -> None:
        with zipfile.ZipFile(source, "w") as zf:
            zf.writestr("a.json", content)

    monkeypatch.setattr(gen, "SCHEMA_URL", source.as_uri())
    publish("{}")
    gen.ensure_schemas(cache)                       # first use downloads
    first = cache.read_bytes()
    publish('{"typeName": "AWS::New::Thing"}')
    gen.ensure_schemas(cache)                       # cached: not downloaded again
    assert cache.read_bytes() == first
    gen.ensure_schemas(cache, refresh=True)         # --refresh picks up the new snapshot
    assert cache.read_bytes() != first
    good = cache.read_bytes()
    monkeypatch.setattr(gen, "SCHEMA_URL", (tmp_path / "missing.zip").as_uri())
    with pytest.raises(OSError):
        gen.ensure_schemas(cache, refresh=True)
    assert cache.read_bytes() == good               # a failed refresh leaves the old cache intact
    assert list(cache.parent.iterdir()) == [cache]  # and no half-downloaded file
