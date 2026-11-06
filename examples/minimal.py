"""The smallest useful program: build a template and print it. Shown in the book."""

# --8<-- [start:main]
import json
from dataclasses import dataclass

import cfn_typed as cfn
from cfn_types import sqs


@dataclass(frozen=True)
class JobsConfig:
    visibility_timeout: int = 60


def build(config: JobsConfig = JobsConfig()) -> cfn.Template:
    params = cfn.Params()
    stage = params.string("Stage", default="dev", allowed_values=["dev", "test", "prod"])
    return {
        "AWSTemplateFormatVersion": "2010-09-09",
        "Parameters": params.declarations(),
        "Resources": {
            "Jobs": sqs.queue(VisibilityTimeout=config.visibility_timeout, Tags=cfn.tags(Stage=stage)),
        },
        "Outputs": {"JobsUrl": {"Value": cfn.ref("Jobs")}},
    }


if __name__ == "__main__":
    print(json.dumps(build(), indent=2))
# --8<-- [end:main]
