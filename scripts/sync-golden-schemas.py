#!/usr/bin/env python3
"""Refresh tests/golden/schemas/ from the upstream CloudFormation registry schemas.

    uv run python scripts/sync-golden-schemas.py             # slice from the cached zip
    uv run python scripts/sync-golden-schemas.py --refresh   # download the latest zip first
    uv run python scripts/sync-golden-schemas.py --schemas s3://BUCKET/KEY

Keeps one schema per type in TYPES, verbatim apart from key order and indentation, and deletes the rest.
Then regenerate the golden modules and review both diffs:

    CFN_TYPED_UPDATE=1 uv run pytest tests/test_golden_types.py
"""

import argparse
import json
import zipfile
from pathlib import Path

from cfn_typed import typegen

TYPES = ["AWS::SQS::Queue", "AWS::Lambda::Function", "AWS::S3::Bucket", "AWS::IAM::Role", "AWS::DynamoDB::Table"]
OUT = Path(__file__).parent.parent / "tests" / "golden" / "schemas"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--schemas", help="CloudformationSchema.zip: a local path or s3://bucket/key (default: AWS's public URL, cached)")
    ap.add_argument("--refresh", action="store_true", help="download the schemas again first")
    args = ap.parse_args()

    zip_path = typegen.ensure_schemas(args.schemas, args.refresh)
    with zipfile.ZipFile(zip_path) as zf:
        by_type = {s["typeName"]: s for s in (json.loads(zf.read(n)) for n in zf.namelist() if n.endswith(".json"))}
    missing = [t for t in TYPES if t not in by_type]
    if missing:
        raise SystemExit(f"not in the schema zip: {', '.join(missing)}")

    OUT.mkdir(parents=True, exist_ok=True)
    keep = {t.lower().replace("::", "-") + ".json" for t in TYPES}
    for old in OUT.glob("*.json"):
        if old.name not in keep:
            old.unlink()
    for t in TYPES:
        (OUT / (t.lower().replace("::", "-") + ".json")).write_text(json.dumps(by_type[t], indent=1, sort_keys=True) + "\n")
    print(f"wrote {len(TYPES)} schemas to {OUT} from {typegen.schema_stamp(zip_path)}")
    print("next: CFN_TYPED_UPDATE=1 uv run pytest tests/test_golden_types.py, then review and commit both diffs")


if __name__ == "__main__":
    main()
