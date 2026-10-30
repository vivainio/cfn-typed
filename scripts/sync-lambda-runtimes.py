#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.12"
# ///
"""Regenerate src/cfn_typed/_lambda_runtimes.py from cfn-lint's Lambda runtime lifecycle data.

    uv run scripts/sync-lambda-runtimes.py

cfn-lint (https://github.com/aws-cloudformation/cfn-lint, MIT-0) keeps these dates up to date as AWS announces them.
Only this script downloads anything; the result is committed.
"""

import json
import urllib.request
from pathlib import Path

URL = "https://raw.githubusercontent.com/aws-cloudformation/cfn-lint/main/src/cfnlint/data/AdditionalSpecs/LmbdRuntimeLifecycle.json"
OUT = Path(__file__).resolve().parent.parent / "src" / "cfn_typed" / "_lambda_runtimes.py"

HEAD = '''"""Lambda runtime support dates: runtime -> (deprecated, create blocked, update blocked, successor), ISO dates or None.

Taken from cfn-lint's LmbdRuntimeLifecycle.json, which follows
https://docs.aws.amazon.com/lambda/latest/dg/runtime-support-policy.html. Refresh with `uv run scripts/sync-lambda-runtimes.py`.
"""

RUNTIMES: dict[str, tuple[str, str | None, str | None, str | None]] = {
'''

with urllib.request.urlopen(URL) as response:
    data = json.load(response)
rows = [f'    {k!r}: ({v["deprecated"]!r}, {v["create-block"]!r}, {v["update-block"]!r}, {v["successor"]!r}),' for k, v in sorted(data.items())]
OUT.write_text(HEAD + "\n".join(rows) + "\n}\n")
print(f"wrote {len(rows)} runtimes to {OUT}")
