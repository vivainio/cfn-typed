"""examples/serverless_eject: the made-up Serverless Framework service the 'Ejecting Serverless' page walks through."""

import importlib
import json
import sys
from pathlib import Path

import pytest

from cfn_typed.testing import assert_references_resolve

EXAMPLE = Path(__file__).parent.parent / "examples" / "serverless_eject"
ORIGINAL = json.loads((EXAMPLE / "original.json").read_text())


@pytest.fixture(autouse=True)
def example_on_path(monkeypatch):
    monkeypatch.syspath_prepend(str(EXAMPLE))
    monkeypatch.syspath_prepend(str(EXAMPLE.parent))
    for name in ("imported", "eject", "with_sls", "with_sls_api"):
        sys.modules.pop(name, None)
    yield
    for name in ("imported", "eject", "with_sls", "with_sls_api"):
        sys.modules.pop(name, None)


def test_the_import_renders_back_to_the_original() -> None:
    assert importlib.import_module("imported").build() == ORIGINAL


def test_the_hand_pass_still_renders_the_original() -> None:
    assert importlib.import_module("eject").build() == ORIGINAL


def test_the_original_is_a_sound_template() -> None:
    assert_references_resolve(ORIGINAL)


def test_the_sls_patterns_render_the_original() -> None:
    assert importlib.import_module("with_sls").build() == ORIGINAL


def test_logical_names_follow_the_frameworks_rule() -> None:
    from cfn_typed_sumo import sls

    assert sls.logical("api_handler") == "ApiUnderscorehandler" and sls.logical("my-fn") == "MyDashfn"


def test_the_usual_events_render_the_original() -> None:
    original = json.loads((EXAMPLE / "original_api.json").read_text())
    assert_references_resolve(original)
    assert importlib.import_module("with_sls_api").build() == original


def test_paths_become_ids_the_way_the_framework_writes_them() -> None:
    from cfn_typed_sumo import sls

    assert [sls.path_id(p) for p in ("/", "/todos", "/todos/{id}", "/{proxy+}", "/my-items")] == ["", "Todos", "TodosIdVar", "ProxyVar", "MyDashitems"]
