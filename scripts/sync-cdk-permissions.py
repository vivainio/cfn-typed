#!/usr/bin/env python3
"""Regenerate src/cfn_typed/permissions.py: IAM action names, taken from the AWS CDK.

    python scripts/sync-cdk-permissions.py                 # at the pinned commit
    python scripts/sync-cdk-permissions.py --sha <commit>  # bump the pin, then review the diff

`Sqs.ReceiveMessage` is the string "sqs:ReceiveMessage", so a typo is an attribute error instead of a
policy that quietly allows nothing. The names are the ones the AWS CDK (Apache-2.0,
https://github.com/aws/aws-cdk) uses in its grants for the major services. Only names are kept: no
prose, no code, and no opinion about which names belong together.

Every name comes from a CDK file fetched at the pinned commit: grants.json files, the constant arrays in
`perms.ts`, or a literal that must appear in the CDK file cited for it (the script stops if it does not).
Nothing is typed in from memory.
"""

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

PINNED_SHA = "21f38da07f18cce95d05a9f93c67861446899fbc"
RAW = "https://raw.githubusercontent.com/aws/aws-cdk/{sha}/packages/aws-cdk-lib/{path}"
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "src" / "cfn_typed" / "permissions.py"

# IAM prefix -> class name (anything else becomes a capitalised prefix)
CLASSES = {
    "s3": "S3", "dynamodb": "DynamoDb", "sqs": "Sqs", "sns": "Sns", "lambda": "Lambda", "kms": "Kms",
    "secretsmanager": "SecretsManager", "ssm": "Ssm", "logs": "Logs", "events": "Events", "kinesis": "Kinesis",
}

# grants.json files: every action and key action in them
JSON_FILES = ["aws-sqs/grants.json", "aws-sns/grants.json", "aws-ssm/grants.json", "aws-logs/grants.json", "aws-events/grants.json"]

# TypeScript files whose `const NAME = [ 'svc:Action', ... ]` arrays are all action lists
CONSTANT_FILES = ["aws-s3/lib/perms.ts", "aws-dynamodb/lib/perms.ts", "aws-kms/lib/private/perms.ts", "aws-kinesis/lib/stream.ts"]

# Actions CDK writes inline in a construct: file -> the actions we take from it (each must appear there)
LITERALS = {
    "aws-lambda/lib/function-base.ts": ["lambda:InvokeFunction"],  # grantInvoke
    "aws-secretsmanager/lib/secret.ts": [  # grantRead, grantWrite
        "secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret",
        "secretsmanager:PutSecretValue", "secretsmanager:UpdateSecret", "secretsmanager:UpdateSecretVersionStage",
    ],
}

ACTION = re.compile(r"^[a-z0-9-]+:[A-Za-z0-9*]+$")


def fetch(sha: str, path: str) -> str:
    with urllib.request.urlopen(RAW.format(sha=sha, path=path), timeout=60) as response:  # noqa: S310 - fixed https host
        return response.read().decode()


def strings_in_arrays(text: str) -> list[str]:
    """Every quoted string inside a `const X = [ ... ];` array (comments removed; spreads add nothing new)."""
    text = re.sub(r"(?m)//.*$", "", text)
    return [s for body in re.findall(r"const\s+\w+\s*=\s*\[(.*?)\];", text, re.S) for s in re.findall(r"'([^']+)'", body)]


def json_actions(text: str) -> list[str]:
    spec = json.loads(text)
    return [a for r in spec["resources"].values() for g in r["grants"].values() for a in g.get("actions", []) + g.get("keyActions", [])]


def collect(sha: str) -> dict[str, set[str]]:
    """action -> the CDK files that mention it"""
    sources: dict[str, set[str]] = {}

    def add(action: str, path: str) -> None:
        if not ACTION.match(action):
            return  # a condition key or other string that merely shares an array with actions
        sources.setdefault(action, set()).add(path)

    for path in JSON_FILES:
        for action in json_actions(fetch(sha, path)):
            add(action, path)
    for path in CONSTANT_FILES:
        for action in strings_in_arrays(fetch(sha, path)):
            add(action, path)
    for path, actions in LITERALS.items():
        text = fetch(sha, path)
        for action in actions:
            if f"'{action}'" not in text:
                sys.exit(f"{action!r} is not in {path} at {sha}")
            add(action, path)
    return sources


def attribute(action: str) -> str:
    """`sqs:ReceiveMessage` -> `ReceiveMessage`; a `*` becomes `_All`, so `s3:GetObject*` is `GetObject_All`."""
    name = action.split(":", 1)[1]
    name = name.replace("*", "_All") if name != "*" else "All"
    if not name.isidentifier():
        sys.exit(f"cannot make an attribute from {action!r}")
    return name


def render(sha: str, sources: dict[str, set[str]]) -> str:
    by_class: dict[str, dict[str, str]] = {}
    files: dict[str, set[str]] = {}
    for action, paths in sources.items():
        prefix = action.split(":", 1)[0]
        cls = CLASSES.get(prefix, prefix.capitalize())
        attr = attribute(action)
        if attr in by_class.setdefault(cls, {}):
            sys.exit(f"two actions become {cls}.{attr}")
        by_class[cls][attr] = action
        files.setdefault(cls, set()).update(paths)
    lines = [
        '"""IAM action names, taken from the AWS CDK.',
        "",
        '    allow([Sqs.ReceiveMessage, Sqs.DeleteMessage], queue_arn)    # "sqs:ReceiveMessage", ...',
        "",
        "A misspelled name is an attribute error, instead of a policy that quietly allows nothing. A `*` in the",
        "IAM action becomes `_All`: `S3.GetObject_All` is `s3:GetObject*`.",
        "",
        "These are the names the AWS CDK uses in its grants for the major services, and only the names. They are",
        "not a complete list of IAM actions: for anything missing, write the string.",
        "",
        f"Source: https://github.com/aws/aws-cdk at commit {sha}",
        "(packages/aws-cdk-lib/...), licensed under the Apache License 2.0. See NOTICE and",
        "licenses/AWS-CDK-LICENSE.txt. Copyright Amazon.com, Inc. or its affiliates.",
        "",
        "Generated by scripts/sync-cdk-permissions.py: do not edit.",
        '"""',
        "# fmt: off",
        "# ruff: noqa",
        "",
        "from typing import Final",
    ]
    for cls in sorted(by_class):
        lines += ["", "", f"class {cls}:", f'    """From: {", ".join(sorted(files[cls]))}"""', ""]
        lines += [f'    {attr}: Final = "{action}"' for attr, action in sorted(by_class[cls].items())]
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--sha", default=PINNED_SHA, help="aws-cdk commit to copy from")
    args = ap.parse_args()
    sources = collect(args.sha)
    OUT.write_text(render(args.sha, sources))
    classes = {a.split(":", 1)[0] for a in sources}
    print(f"wrote {OUT.relative_to(ROOT)}: {len(sources)} names in {len(classes)} services, {OUT.stat().st_size} bytes (cdk {args.sha[:10]})")
    if args.sha != PINNED_SHA:
        print(f"update PINNED_SHA in this script to {args.sha} if you keep this result")


if __name__ == "__main__":
    main()
