"""`cfn-typed import`: a template becomes Python that renders to the same template."""

import importlib
import json
import sys
from pathlib import Path

import pytest

from cfn_typed import importer, typegen
from cfn_typed.cli import main

FIXTURE = Path(__file__).parent / "fixtures" / "sls-package.json"


@pytest.fixture
def types(tmp_path, monkeypatch):
    typegen.main(["--out", str(tmp_path / "imp_types"), "--no-docs", "--template", str(FIXTURE)])
    monkeypatch.syspath_prepend(str(tmp_path))
    yield "imp_types"
    for name in [n for n in sys.modules if n.startswith("imp_types") or n == "imported_stack"]:
        del sys.modules[name]


def load(source: str, tmp_path):
    (tmp_path / "imported_stack.py").write_text(source)
    return importlib.import_module("imported_stack")


def test_round_trip_is_exact(types, tmp_path) -> None:
    original = json.loads(FIXTURE.read_text())
    module = load(importer.to_python(original, types), tmp_path)
    assert module.build() == original


def test_resources_use_factories_and_builders(types) -> None:
    source = importer.to_python(json.loads(FIXTURE.read_text()), types)
    assert "from imp_types import" in source
    assert "sqs.queue(" in source and "lambda_.function(" in source
    assert 'cfn.get_att("OrdersQueue", "Arn")' in source
    assert 'deletion_policy="Retain"' in source


def test_unfactoried_resources_stay_dicts_with_a_reason(types) -> None:
    source = importer.to_python(json.loads(FIXTURE.read_text()), types)
    assert "# kept as a dict: no generated factory for this type" in source
    assert "Cleanup: kept as a dict" in source


def test_creation_policy_keeps_the_resource_a_dict() -> None:
    template = {"Resources": {"G": {"Type": "AWS::AutoScaling::AutoScalingGroup", "CreationPolicy": {"ResourceSignal": {"Count": 1}}}}}
    assert "keys the factories do not take: CreationPolicy" in importer.to_python(template)


def test_unusual_intrinsic_shapes_stay_dicts() -> None:
    template = {"Resources": {}, "Outputs": {"X": {"Value": {"Fn::Join": ["", "x", "y"]}, "Description": {"Fn::Transform": {"Name": "m"}}}}}
    source = importer.to_python(template)
    assert '"Fn::Transform"' in source and "cfn.join" not in source


def test_dotted_getatt_string_form() -> None:
    assert 'cfn.get_att("A", "Arn")' in importer.to_python({"Outputs": {"X": {"Value": {"Fn::GetAtt": "A.Arn"}}}})


def test_cli_import_writes_a_module(types, tmp_path, capsys) -> None:
    out = tmp_path / "stack.py"
    assert main(argv=["import", str(FIXTURE), "-o", str(out), "--types", types], prog="cfn-typed") == 0
    assert "def build() -> cfn.Template:" in out.read_text()


def test_cli_import_missing_file(tmp_path) -> None:
    with pytest.raises(SystemExit) as e:
        main(argv=["import", str(tmp_path / "nope.json")], prog="cfn-typed")
    assert e.value.code == 2


def test_typegen_template_skips_custom_resources() -> None:
    assert typegen.template_types(FIXTURE) == sorted(t for t in typegen.template_types(FIXTURE) if not t.startswith("Custom::"))
    assert "Custom::Cleanup" not in typegen.template_types(FIXTURE)
