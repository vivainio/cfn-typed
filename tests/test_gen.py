from typing import Any

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
