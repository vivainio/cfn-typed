"""The repo ships no generated types; regenerate the ones the examples use before tests import them."""

from pathlib import Path

from cfn_typed import typegen

EXAMPLES = Path(__file__).parent.parent / "examples"

types = [t for t in (EXAMPLES / "types.txt").read_text().split("\n") if t and not t.startswith("#")]
typegen.main(["--out", str(EXAMPLES / "cfn_types"), "--no-docs", *types])
