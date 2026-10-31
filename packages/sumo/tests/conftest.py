"""The repo ships no generated types; generate them before tests import `cfn_typed_sumo`."""

from pathlib import Path

from cfn_typed import typegen

typegen.main(["--config", str(Path(__file__).parent.parent / "cfn-typegen.toml")])
