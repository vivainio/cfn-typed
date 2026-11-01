# --8<-- [start:main]
import sys

import cfn_types
from cfn_typed import cli
from stacks import buckets, orders


def main() -> int:
    return cli.main({**orders.stacks(), **buckets.stacks()}, schemas=cfn_types)


if __name__ == "__main__":
    sys.exit(main())
# --8<-- [end:main]
