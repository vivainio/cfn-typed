"""The rendered examples are committed in examples/rendered/. CI fails if the code stops producing them.

Intended change? Regenerate and review the diff:  CFN_TYPED_UPDATE=1 uv run pytest tests/test_golden.py
"""

import runpy
import sys
from pathlib import Path
from typing import Any

EXAMPLES = Path(__file__).parent.parent / "examples"
RENDERED = EXAMPLES / "rendered"
sys.path.insert(0, str(EXAMPLES))

import cfn_types  # noqa: E402
import data_consumer  # noqa: E402
import data_platform  # noqa: E402
import intrinsics_demo  # noqa: E402
import minimal  # noqa: E402
import serverless  # noqa: E402
import web_stack  # noqa: E402

from cfn_typed.testing import assert_constraints_hold, assert_matches_file, assert_references_resolve  # noqa: E402


def check(template: Any, name: str) -> None:
    assert_references_resolve(template)
    assert_constraints_hold(template, cfn_types)
    assert_matches_file(template, RENDERED / name)


def test_minimal_prod() -> None:
    check(minimal.build("prod"), "minimal-prod.yaml")


def test_web_stack() -> None:
    check(web_stack.build(), "web-stack.yaml")


def test_sqs_worker_prod() -> None:
    sys.argv = ["sqs_worker.py", "prod"]
    template: Any = runpy.run_path(str(EXAMPLES / "sqs_worker.py"))["template"]
    check(template, "sqs-worker-prod.yaml")


def test_data_platform() -> None:
    check(data_platform.build(), "data-platform.yaml")


def test_data_consumer() -> None:
    check(data_consumer.build(), "data-consumer.yaml")


def test_intrinsics_demo() -> None:
    check(intrinsics_demo.build(), "intrinsics.yaml")


def test_serverless() -> None:
    check(serverless.build(), "serverless.yaml")
