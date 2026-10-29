import json
import runpy
import sys
from pathlib import Path
from typing import Any

import yaml

import cfn_typed as cfn

EXAMPLES = Path(__file__).parent.parent / "examples"


def _construct(loader: yaml.SafeLoader, suffix: str, node: yaml.Node) -> dict[str, Any]:
    """Inverse of the short forms: `!Ref X` -> {"Ref": "X"}, `!GetAtt A.Arn` -> {"Fn::GetAtt": ["A", "Arn"]}."""
    if isinstance(node, yaml.ScalarNode):
        value: Any = loader.construct_scalar(node)
    elif isinstance(node, yaml.SequenceNode):
        value = loader.construct_sequence(node, deep=True)
    elif isinstance(node, yaml.MappingNode):
        value = loader.construct_mapping(node, deep=True)
    else:
        raise TypeError(node)
    if suffix == "GetAtt" and isinstance(value, str):
        value = value.split(".", 1)
    return {"Ref" if suffix == "Ref" else f"Fn::{suffix}": value}


class Loader(yaml.SafeLoader):
    pass


Loader.add_multi_constructor("!", _construct)


def load(text: str) -> Any:
    return yaml.load(text, Loader=Loader)  # noqa: S506 - subclass of SafeLoader


def test_example_template_round_trips() -> None:
    sys.argv = ["sqs_worker.py", "prod"]
    sys.path.insert(0, str(EXAMPLES))
    template = runpy.run_path(str(EXAMPLES / "sqs_worker.py"))["template"]
    text = cfn.to_yaml(template)
    assert load(text) == template == json.loads(cfn.to_json(template))
    assert "!GetAtt OrderDLQ.Arn" in text and "!Ref OrderQueue" in text
    assert "&id" not in text  # the tag list is shared between resources but never anchored


def test_awkward_values_round_trip() -> None:
    user_data = "#!/bin/bash\necho hello\nexport A=1\n"
    template = {
        "Resources": {
            "I": {"Type": "AWS::EC2::Instance", "Properties": {
                "UserData": {"Fn::Base64": {"Fn::Sub": user_data}},          # short forms must not nest directly
                "Names": {"Fn::Join": [",", [cfn.ref("A"), cfn.get_att("B", "Arn")]]},
                "Plain": "yes", "Version": "2012-10-17", "Port": 80, "On": True, "Empty": [],
                "Attr": {"Fn::GetAtt": ["B", cfn.ref("Which")]},              # dynamic attribute stays a list
                "Len": {"Fn::Length": [1, 2]},                                # no short form: stays long
            }},
        },
    }
    text = cfn.to_yaml(template)
    assert load(text) == template
    assert "Fn::Base64:" in text and "!Sub |" in text
    assert "UserData: !Base64" not in text
