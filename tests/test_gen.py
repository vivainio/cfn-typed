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
        "Odd-Key": {"type": "boolean"},
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
