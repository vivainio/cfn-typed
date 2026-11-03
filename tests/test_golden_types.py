"""The generator's output for a fixed set of resources is committed in tests/golden/types/, so a change to
the generator shows up as a readable diff of Python files, and CI fails if the diff was not intended.

The input is pinned too (tests/golden/schemas/, a copy of five registry schemas), so a new AWS schema
snapshot never changes these files, only a change to the generator does.

Intended change? Regenerate and review the diff:  CFN_TYPED_UPDATE=1 uv run pytest tests/test_golden_types.py
"""

import os
import re
import zipfile
from pathlib import Path

from cfn_typed import typegen as gen

GOLDEN = Path(__file__).parent / "golden"
TYPES = GOLDEN / "types"
SNAPSHOT = re.compile(r"^# Schema snapshot: .*\n", re.M)  # the hash of the zip we just built, not of the generator's output


def generate(tmp_path: Path) -> Path:
    zip_path = tmp_path / "schemas.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        for schema in sorted((GOLDEN / "schemas").glob("*.json")):
            zf.write(schema, schema.name)
    out = tmp_path / "types"
    gen.main(["--out", str(out), "--schemas", str(zip_path), "AWS::*"])
    return out


def test_generated_modules_match_the_golden_files(tmp_path: Path) -> None:
    out = generate(tmp_path)
    made = {p.name: SNAPSHOT.sub("", p.read_text()) for p in sorted(out.glob("*.py"))}
    if os.environ.get("CFN_TYPED_UPDATE") == "1":
        TYPES.mkdir(parents=True, exist_ok=True)
        for old in TYPES.glob("*.py"):
            old.unlink()
        for name, text in made.items():
            (TYPES / name).write_text(text)
        return
    golden = {p.name: p.read_text() for p in sorted(TYPES.glob("*.py"))}
    assert sorted(made) == sorted(golden), "different set of generated files: CFN_TYPED_UPDATE=1 to regenerate"
    for name in made:
        assert made[name] == golden[name], f"{name} differs from tests/golden/types/{name}: CFN_TYPED_UPDATE=1 to regenerate"
