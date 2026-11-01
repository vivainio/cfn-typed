"""The same made-up service, written with `cfn_typed_sumo.sls`: the framework's resources under the framework's IDs.

`build()` renders to exactly `original.json` (tests/test_serverless_eject_example.py), so a deploy of it changes nothing.
"""

# --8<-- [start:stack]
from cfn_typed_sumo import sls

import cfn_typed as cfn

SERVICE, STAGE = "ledger", "dev"


def build() -> cfn.Template:
    worker = sls.function(
        "worker",
        service=SERVICE,
        stage=STAGE,
        s3_key="serverless/ledger/dev/1730000000000-2026-10-31T10:00:00.000Z/ledger.zip",
        handler="handler.cleanup",
        runtime="python3.12",
        memory=512,
        timeout=600,
        log_retention_days=30,
        code_sha256="abc123def456abc123def456abc123def456abc123def456abc123def456abcd",
        version_id="Abc123def456",
    )
    return {
        "AWSTemplateFormatVersion": "2010-09-09",
        "Description": "The AWS CloudFormation template for this Serverless application",
        "Resources": cfn.combine(
            sls.deployment_bucket(),
            sls.iam_role(SERVICE, STAGE),
            worker,
            sls.schedule_event("worker", "cron(0 3 * * ? *)"),
        ),
        "Outputs": sls.outputs(SERVICE, STAGE, worker),
    }
# --8<-- [end:stack]
