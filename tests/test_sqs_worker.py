import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "examples"))

import cfn_typed as cfn  # noqa: E402
from cfn_types import sqs  # noqa: E402


def test_factories_return_plain_dicts() -> None:
    assert cfn.get_att("A", "Arn") == {"Fn::GetAtt": ["A", "Arn"]}
    assert sqs.queue(VisibilityTimeout=60, condition="Prod") == {
        "Type": "AWS::SQS::Queue",
        "Properties": {"VisibilityTimeout": 60},
        "Condition": "Prod",
    }
    assert sqs.queue() == {"Type": "AWS::SQS::Queue"}


def test_example_renders_valid_json() -> None:
    out = subprocess.run(
        [sys.executable, str(ROOT / "examples" / "sqs_worker.py"), "prod"],
        check=True, capture_output=True, text=True,
    ).stdout
    resources = json.loads(out)["Resources"]
    assert set(resources) == {
        "ExecutionRole", "Processor", "ProcessorEventSourceMapping", "OrderDLQ", "OrderQueue",
    }
    assert resources["Processor"]["Properties"]["FunctionName"] == "order-processor-prod-processor"


def test_minimal_main_prints_a_template() -> None:
    out = subprocess.run(
        [sys.executable, str(ROOT / "examples" / "minimal.py"), "prod"],
        check=True, capture_output=True, text=True,
    ).stdout
    template = json.loads(out)
    assert template["Resources"]["Jobs"]["Properties"]["Tags"] == [{"Key": "Stage", "Value": "prod"}]
