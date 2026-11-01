# --8<-- [start:test]
import cfn_types
from cfn_typed import cli
from cfn_typed.testing import assert_matches_file
from main import main  # noqa: F401  (the stacks, as the command line sees them)
from stacks import buckets, orders


def test_orders() -> None:
    assert_matches_file(orders.build(), orders.HERE.parent / "rendered/orders.yaml")


def test_every_stack_matches_its_committed_file() -> None:
    stacks = {**orders.stacks(), **buckets.stacks()}
    assert cli.main(stacks, schemas=cfn_types, argv=["diff"]) == 0
    assert cli.main(stacks, schemas=cfn_types, argv=["check"]) == 0
# --8<-- [end:test]
