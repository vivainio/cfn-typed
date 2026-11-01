from pathlib import Path

import pytest

from cfn_typed import code, ref


def test_s3_is_the_bucket_and_key() -> None:
    assert code.s3("artifacts", "worker/abc123.zip") == {"S3Bucket": "artifacts", "S3Key": "worker/abc123.zip"}


def test_s3_takes_intrinsics_and_a_version() -> None:
    c = code.s3(ref("Bucket"), ref("CodeKey"), version="v1")
    assert c == {"S3Bucket": ref("Bucket"), "S3Key": ref("CodeKey"), "S3ObjectVersion": "v1"}


def test_local_is_a_plain_path_for_package() -> None:
    assert code.local("dist/worker.zip") == "dist/worker.zip"
    assert code.local(Path("dist") / "worker.zip") == "dist/worker.zip"


def test_inline_is_zipfile() -> None:
    assert code.inline("def handler(e, c): pass") == {"ZipFile": "def handler(e, c): pass"}


def test_inline_is_limited_to_4096_characters() -> None:
    code.inline("x" * 4096)
    with pytest.raises(ValueError, match="4097"):
        code.inline("x" * 4097)


def test_inline_file_reads_the_source_at_render_time(tmp_path: Path) -> None:
    src = "def handler(event, context):\n    return 1\n"
    (tmp_path / "notify.py").write_text(src)
    assert code.inline_file(tmp_path / "notify.py") == {"ZipFile": src}


def test_inline_file_rejects_a_python_syntax_error(tmp_path: Path) -> None:
    (tmp_path / "bad.py").write_text("def handler(:\n")
    with pytest.raises(SyntaxError):
        code.inline_file(tmp_path / "bad.py")


def test_inline_file_does_not_parse_other_languages(tmp_path: Path) -> None:
    (tmp_path / "index.js").write_text("exports.handler = async () => 1;\n")
    assert "ZipFile" in code.inline_file(tmp_path / "index.js")
