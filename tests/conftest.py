"""The repo ships no generated types; generate the ones the examples use before tests import them."""

from pathlib import Path

from cfn_typed import typegen

EXAMPLES = Path(__file__).parent.parent / "examples"
OUT = EXAMPLES / "cfn_types"

if not OUT.exists():
    types = [t for t in (EXAMPLES / "types.txt").read_text().split("\n") if t and not t.startswith("#")]
    typegen.main(["--out", str(OUT), *types])
