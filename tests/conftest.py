"""The repo ships no generated types; regenerate them (the examples' and sumo's) before tests import them."""

from pathlib import Path

from cfn_typed import typegen

EXAMPLES = Path(__file__).parent.parent / "examples"

typegen.main(["--config", str(EXAMPLES / "cfn-typegen.toml")])
typegen.main(["--config", str(EXAMPLES.parent / "packages" / "sumo" / "cfn-typegen.toml")])  # the examples import cfn_typed_sumo
