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

import data_consumer  # noqa: E402
import data_platform  # noqa: E402
import intrinsics_demo  # noqa: E402
import minimal  # noqa: E402
import web_stack  # noqa: E402

from cfn_typed.testing import assert_matches_file  # noqa: E402


def test_minimal_prod() -> None:
    assert_matches_file(minimal.build("prod"), RENDERED / "minimal-prod.yaml")


def test_web_stack() -> None:
    assert_matches_file(web_stack.build(), RENDERED / "web-stack.yaml")


def test_sqs_worker_prod() -> None:
    sys.argv = ["sqs_worker.py", "prod"]
    template: Any = runpy.run_path(str(EXAMPLES / "sqs_worker.py"))["template"]
    assert_matches_file(template, RENDERED / "sqs-worker-prod.yaml")


def test_data_platform() -> None:
    assert_matches_file(data_platform.build(), RENDERED / "data-platform.yaml")


def test_data_consumer() -> None:
    assert_matches_file(data_consumer.build(), RENDERED / "data-consumer.yaml")


def test_intrinsics_demo() -> None:
    assert_matches_file(intrinsics_demo.build(), RENDERED / "intrinsics.yaml")
