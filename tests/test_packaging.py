import json
import zipfile
from pathlib import Path
from typing import Any

import pytest

from cfn_typed.packaging import WSGI_FILES, call_handler, find_missing_code, find_wsgi_problems, find_zip_problems, wsgi_config
from cfn_typed.testing import assert_code_exists, assert_wsgi_package_ok, assert_zip_ok


def make_zip(path: Path, files: dict[str, str]) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        for name, text in files.items():
            archive.writestr(name, text)
    return path


APP = "def handler(event, context):\n    return {'statusCode': 200, 'body': event.get('path', '')}\n"
WSGI = {"wsgi_handler.py": "from serverless_wsgi import *\n", "serverless_wsgi.py": "x = 1\n", ".serverless-wsgi": wsgi_config("api.app"), "api.py": "app = object()\n"}


def test_a_sound_zip_has_no_problems(tmp_path: Path) -> None:
    zipped = make_zip(tmp_path / "a.zip", {"app.py": APP, "pkg/__init__.py": "def run(): ...\n"})
    assert find_zip_problems(zipped, ["app.py"], handler="app.handler") == []
    assert find_zip_problems(zipped, handler="pkg.run") == []
    assert_zip_ok(zipped, ["app.py"], handler="app.handler")


def test_missing_files_modules_and_functions_are_reported(tmp_path: Path) -> None:
    zipped = make_zip(tmp_path / "a.zip", {"app.py": APP, "bad.py": "def (:\n"})
    assert find_zip_problems(zipped, ["other.py"]) == [f"{zipped}: missing other.py"]
    assert "no nope.py" in find_zip_problems(zipped, handler="nope.handler")[0]
    assert "does not define 'run'" in find_zip_problems(zipped, handler="app.run")[0]
    assert "does not parse" in find_zip_problems(zipped, handler="bad.handler")[0]
    assert "not module.function" in find_zip_problems(zipped, handler="handler")[0]
    with pytest.raises(AssertionError, match="missing other.py"):
        assert_zip_ok(zipped, ["other.py"])


def test_a_file_that_is_not_a_zip_is_a_problem(tmp_path: Path) -> None:
    (tmp_path / "x.zip").write_text("nope")
    assert "cannot read the zip" in find_zip_problems(tmp_path / "x.zip")[0]
    assert "cannot read the zip" in find_zip_problems(tmp_path / "gone.zip")[0]


def test_the_wsgi_plugins_three_files_are_required(tmp_path: Path) -> None:
    assert find_wsgi_problems(make_zip(tmp_path / "ok.zip", WSGI), app="api.app") == []
    assert_wsgi_package_ok(make_zip(tmp_path / "ok2.zip", WSGI))
    for gone in WSGI_FILES:
        zipped = make_zip(tmp_path / f"no{gone}.zip", {k: v for k, v in WSGI.items() if k != gone})
        assert any(f"missing {gone}" in p for p in find_wsgi_problems(zipped)), gone
    with pytest.raises(AssertionError, match="WSGI package"):
        assert_wsgi_package_ok(make_zip(tmp_path / "empty.zip", {"api.py": ""}))


def test_the_wsgi_config_must_name_a_module_in_the_zip(tmp_path: Path) -> None:
    wrong = make_zip(tmp_path / "w.zip", {**WSGI, ".serverless-wsgi": wsgi_config("other.app")})
    assert any("no other.py" in p for p in find_wsgi_problems(wrong))
    assert any("expected 'api.app'" in p for p in find_wsgi_problems(wrong, app="api.app"))
    assert any("not JSON" in p for p in find_wsgi_problems(make_zip(tmp_path / "j.zip", {**WSGI, ".serverless-wsgi": "{"})))
    assert any("no 'app'" in p for p in find_wsgi_problems(make_zip(tmp_path / "n.zip", {**WSGI, ".serverless-wsgi": "{}"})))
    assert json.loads(wsgi_config("api.app", text_mime_types=["application/json"])) == {"app": "api.app", "text_mime_types": ["application/json"]}


def test_the_handler_is_called_once_in_a_fresh_interpreter(tmp_path: Path) -> None:
    zipped = make_zip(tmp_path / "a.zip", {"app.py": APP + "import os\ndef env(e, c):\n    return os.environ['X']\n\ndef boom(e, c):\n    raise RuntimeError('no')\n"})
    assert call_handler(zipped, "app.handler", {"path": "/health"}) == {"statusCode": 200, "body": "/health"}
    assert call_handler(zipped, "app.env", {}, env={"X": "1"}) == "1"
    with pytest.raises(AssertionError, match="RuntimeError: no"):
        call_handler(zipped, "app.boom", {})


TEMPLATE: dict[str, Any] = {"Resources": {
    "A": {"Type": "AWS::Lambda::Function", "Properties": {"Code": {"S3Bucket": {"Ref": "Bucket"}, "S3Key": "k/a.zip"}}},
    "B": {"Type": "AWS::Lambda::Function", "Properties": {"Code": {"S3Bucket": {"Ref": "Bucket"}, "S3Key": "k/a.zip"}}},
    "C": {"Type": "AWS::Lambda::Function", "Properties": {"Code": {"S3Bucket": "fixed", "S3Key": "k/c.zip"}}},
    "L": {"Type": "AWS::Lambda::LayerVersion", "Properties": {"Content": {"S3Bucket": "fixed", "S3Key": "k/l.zip"}}},
    "Inline": {"Type": "AWS::Lambda::Function", "Properties": {"Code": {"ZipFile": "x"}}},
}}


def test_missing_s3_code_is_reported_once_per_object() -> None:
    asked: list[tuple[str, str]] = []

    def exists(bucket: str, key: str) -> bool:
        asked.append((bucket, key))
        return key != "k/c.zip"

    problems = find_missing_code(TEMPLATE, exists, buckets={"Bucket": "real"})
    assert problems == ["Resources.C.Properties.Code: s3://fixed/k/c.zip does not exist"]
    assert asked.count(("real", "k/a.zip")) == 1 and len(asked) == 3
    with pytest.raises(AssertionError, match="s3://fixed/k/c.zip"):
        assert_code_exists(TEMPLATE, exists, buckets={"Bucket": "real"})


def test_an_unnamed_bucket_is_reported_not_guessed() -> None:
    problems = find_missing_code(TEMPLATE, lambda b, k: True)
    assert len(problems) == 2 and all("not given a name" in p for p in problems)
