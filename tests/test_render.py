import json
import runpy
import sys
from pathlib import Path
from typing import Any

import cfn_typed as cfn
from cfn_typed.cli import parse_template

EXAMPLES = Path(__file__).parent.parent / "examples"


def load(text: str) -> Any:
    return parse_template(text)


def test_example_template_round_trips() -> None:
    sys.path.insert(0, str(EXAMPLES))
    import sqs_worker

    template = sqs_worker.build()
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


def test_an_empty_string_after_a_short_form_is_written_out() -> None:
    text = cfn.to_yaml({"Resources": {"R": {"Type": "AWS::X::Y", "Properties": {"Zones": cfn.get_azs(), "Here": cfn.get_azs(cfn.ref("AWS::Region"))}}}})
    assert "Zones: !GetAZs ''" in text
    assert load(text)["Resources"]["R"]["Properties"]["Zones"] == {"Fn::GetAZs": ""}  # not null


def test_conditions_and_the_functions_round_trip() -> None:
    sys.path.insert(0, str(EXAMPLES))
    from intrinsics_demo import build

    template = build()
    assert load(cfn.to_yaml(template)) == json.loads(cfn.to_json(template))
