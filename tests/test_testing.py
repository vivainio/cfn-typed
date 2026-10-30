from pathlib import Path
from typing import Any

import pytest

from cfn_typed.testing import UPDATE_ENV, assert_matches_file, render_for

TEMPLATE: dict[str, Any] = {"Resources": {"Q": {"Type": "AWS::SQS::Queue", "Properties": {"VisibilityTimeout": 30}}}}


def test_a_matching_file_passes_and_json_is_chosen_by_suffix(tmp_path: Path) -> None:
    yaml_path, json_path = tmp_path / "t.yaml", tmp_path / "t.json"
    assert_matches_file(TEMPLATE, yaml_path, update=True)
    assert_matches_file(TEMPLATE, json_path, update=True)
    assert_matches_file(TEMPLATE, yaml_path, update=False)
    assert_matches_file(TEMPLATE, json_path, update=False)
    assert json_path.read_text().startswith("{") and yaml_path.read_text().startswith("Resources:")
    assert render_for(json_path, TEMPLATE).endswith("}\n")


def test_json_can_be_indented_with_tabs(tmp_path: Path) -> None:
    path = tmp_path / "t.json"
    assert_matches_file(TEMPLATE, path, update=True, indent="\t")
    assert path.read_text().splitlines()[1].startswith('\t"Resources"')
    assert_matches_file(TEMPLATE, path, update=False, indent="\t")
    with pytest.raises(AssertionError, match="differs"):
        assert_matches_file(TEMPLATE, path, update=False)  # the default of two spaces is a different file
    # nothing in a tab-indented file is trailing whitespace, CRLF or space-indented
    text = path.read_text()
    assert "\r" not in text and text.endswith("}\n") and all(line == line.rstrip() and " " not in line[: len(line) - len(line.lstrip())] for line in text.splitlines())


def test_a_difference_fails_with_a_line_diff_and_the_way_to_accept_it(tmp_path: Path) -> None:
    path = tmp_path / "t.yaml"
    assert_matches_file(TEMPLATE, path, update=True)
    changed = {"Resources": {"Q": {"Type": "AWS::SQS::Queue", "Properties": {"VisibilityTimeout": 60}}}}
    with pytest.raises(AssertionError) as err:
        assert_matches_file(changed, path, update=False)
    message = str(err.value)
    assert "-      VisibilityTimeout: 30" in message and "+      VisibilityTimeout: 60" in message
    assert UPDATE_ENV in message
    assert "VisibilityTimeout: 30" in path.read_text()  # a failing check leaves the file alone


def test_a_missing_file_fails_instead_of_being_created(tmp_path: Path) -> None:
    path = tmp_path / "new" / "t.yaml"
    with pytest.raises(AssertionError, match="does not exist"):
        assert_matches_file(TEMPLATE, path, update=False)
    assert not path.exists()


def test_the_environment_variable_switches_to_update_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "t.yaml"
    monkeypatch.setenv(UPDATE_ENV, "1")
    assert_matches_file(TEMPLATE, path)
    assert path.exists()
    monkeypatch.delenv(UPDATE_ENV)
    assert_matches_file(TEMPLATE, path)  # same content: passes without update mode
