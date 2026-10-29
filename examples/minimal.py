"""The smallest useful program: build a template and print it. Shown in the book."""

# --8<-- [start:main]
import json
import sys

import cfn_typed as cfn
from cfn_types import sqs


def build(stage: str) -> cfn.Template:
    return {
        "AWSTemplateFormatVersion": "2010-09-09",
        "Resources": {
            "Jobs": sqs.queue(VisibilityTimeout=60, Tags=cfn.tags(Stage=stage)),
        },
        "Outputs": {"JobsUrl": {"Value": cfn.ref("Jobs")}},
    }


def main() -> None:
    stage = sys.argv[1] if len(sys.argv) > 1 else "dev"
    print(json.dumps(build(stage), indent=2))


if __name__ == "__main__":
    main()
# --8<-- [end:main]
