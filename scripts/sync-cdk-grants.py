#!/usr/bin/env python3
"""Regenerate src/cfn_typed/_cdk_grants.py: the AWS CDK's permission sets, as `cfn_typed.grants`.

    python scripts/sync-cdk-grants.py                 # at the pinned commit
    python scripts/sync-cdk-grants.py --sha <commit>  # bump the pin (and the one in sync-cdk-permissions.py)

This is the opinion layer. The AWS CDK (Apache-2.0, https://github.com/aws/aws-cdk) decides which actions
belong together for `grantRead`, `grantWrite`, `grantConsumeMessages`, ... and on which resources; this copies
those decisions for the major services, and says so. The names themselves live in `cfn_typed.permissions`.

Everything comes from CDK files fetched at the pinned commit. Sets in a grants.json are taken as they are.
For sets that CDK composes in code, the entries below record how it combines its constants (the comments
cite the method), constants such as `BUCKET_READ_ACTIONS` are resolved from CDK's `perms.ts`, and a literal
must appear in the CDK file cited for it. Every action must already be a name in `cfn_typed.permissions`,
and the generated module refers to those names, so it cannot contain an action that is not one.
"""

import argparse
import importlib.util
import json
import re
import sys
import urllib.request
from pathlib import Path

PINNED_SHA = "21f38da07f18cce95d05a9f93c67861446899fbc"
RAW = "https://raw.githubusercontent.com/aws/aws-cdk/{sha}/packages/aws-cdk-lib/{path}"
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "src" / "cfn_typed" / "_cdk_grants.py"

# Services that CDK describes in a grants.json: (class, directory)
JSON_SERVICES = [("Sqs", "aws-sqs"), ("Sns", "aws-sns"), ("Ssm", "aws-ssm"), ("Logs", "aws-logs"), ("Events", "aws-events")]

# Sets that CDK composes in code. Each grant is (actions, key_actions, shape): an UPPER_CASE name is a constant
# from `files`, a string with ":" is a literal action. `shape` says which resources the CDK applies it to.
COMPOSED = [
    {
        "service": "S3", "resource": "Bucket",
        "files": ["aws-s3/lib/perms.ts"], "cite": ["aws-s3/lib/bucket-grants.ts"],
        "grants": {  # bucket-grants.ts: actionsOnBucketAndObjectKeys (bucket and objects) / actionsOnObjectKeys (objects)
            "read": (["BUCKET_READ_ACTIONS"], ["KEY_READ_ACTIONS"], "arn_and_objects"),
            "put": (["BUCKET_PUT_ACTIONS"], ["KEY_WRITE_ACTIONS"], "objects"),
            "delete": (["BUCKET_DELETE_ACTIONS"], [], "objects"),
            "write": (["BUCKET_DELETE_ACTIONS", "BUCKET_PUT_ACTIONS"], ["KEY_WRITE_ACTIONS"], "arn_and_objects"),
            "put_acl": (["BUCKET_PUT_ACL_ACTIONS"], [], "objects"),
            "read_write": (["BUCKET_READ_ACTIONS", "BUCKET_DELETE_ACTIONS", "BUCKET_PUT_ACTIONS"],
                           ["KEY_READ_ACTIONS", "KEY_WRITE_ACTIONS"], "arn_and_objects"),
        },
    },
    {
        "service": "DynamoDb", "resource": "Table",
        "files": ["aws-dynamodb/lib/perms.ts"], "cite": ["aws-dynamodb/lib/table-grants.ts", "aws-dynamodb/lib/stream-grants.ts"],
        "grants": {  # table-grants.ts readData/writeData/readWriteData/fullAccess; stream-grants.ts read (on the stream ARN)/list
            "read_data": (["RESOURCE_READ_DATA_ACTIONS", "PRINCIPAL_ONLY_READ_DATA_ACTIONS", "DESCRIBE_TABLE"],
                          ["KEY_READ_ACTIONS"], "arn_and_indexes"),
            "write_data": (["WRITE_DATA_ACTIONS", "DESCRIBE_TABLE"], ["KEY_READ_ACTIONS", "KEY_WRITE_ACTIONS"], "arn_and_indexes"),
            "read_write_data": (["RESOURCE_READ_DATA_ACTIONS", "WRITE_DATA_ACTIONS", "PRINCIPAL_ONLY_READ_DATA_ACTIONS", "DESCRIBE_TABLE"],
                                ["KEY_READ_ACTIONS", "KEY_WRITE_ACTIONS"], "arn_and_indexes"),
            "full_access": (["dynamodb:*"], ["KEY_READ_ACTIONS", "KEY_WRITE_ACTIONS"], "arn_and_indexes"),
            "stream_read": (["READ_STREAM_DATA_ACTIONS"], ["KEY_READ_ACTIONS"], "arn"),  # pass the stream ARN
            "list_streams": (["dynamodb:ListStreams"], [], "any"),
        },
    },
    {
        "service": "Kms", "resource": "Key",
        "files": ["aws-kms/lib/private/perms.ts"], "cite": ["aws-kms/lib/key-grants.ts"],
        "grants": {  # key-grants.ts
            "admin": (["ADMIN_ACTIONS"], [], "arn"),
            "decrypt": (["DECRYPT_ACTIONS"], [], "arn"),
            "encrypt": (["ENCRYPT_ACTIONS"], [], "arn"),
            "encrypt_decrypt": (["DECRYPT_ACTIONS", "ENCRYPT_ACTIONS"], [], "arn"),
            "sign": (["SIGN_ACTIONS"], [], "arn"),
            "verify": (["VERIFY_ACTIONS"], [], "arn"),
            "sign_verify": (["SIGN_ACTIONS", "VERIFY_ACTIONS"], [], "arn"),
            "generate_mac": (["GENERATE_HMAC_ACTIONS"], [], "arn"),
            "verify_mac": (["VERIFY_HMAC_ACTIONS"], [], "arn"),
        },
    },
    {
        "service": "Kinesis", "resource": "Stream",
        "files": ["aws-kinesis/lib/stream.ts", "aws-kms/lib/private/perms.ts"], "cite": ["aws-kinesis/lib/stream.ts"],
        "grants": {  # stream.ts grantRead/grantWrite/grantReadWrite, and the key grants they make
            "read": (["READ_OPERATIONS"], ["DECRYPT_ACTIONS"], "arn"),
            "write": (["WRITE_OPERATIONS"], ["ENCRYPT_ACTIONS"], "arn"),
            "read_write": (["READ_OPERATIONS", "WRITE_OPERATIONS"], ["DECRYPT_ACTIONS", "ENCRYPT_ACTIONS"], "arn"),
        },
    },
    {
        "service": "Lambda", "resource": "Function",
        "files": [], "cite": ["aws-lambda/lib/function-base.ts"],
        "grants": {"invoke": (["lambda:InvokeFunction"], [], "arn")},  # grantInvoke: resourceArns = [functionArn]
    },
    {
        "service": "SecretsManager", "resource": "Secret",
        "files": [], "cite": ["aws-secretsmanager/lib/secret.ts"],
        "grants": {  # secret.ts grantRead / grantWrite
            "read": (["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"], [], "arn"),
            "write": (["secretsmanager:PutSecretValue", "secretsmanager:UpdateSecret", "secretsmanager:UpdateSecretVersionStage"], [], "arn"),
        },
    },
]

Entry = tuple[tuple[str, ...], tuple[str, ...], str]


def fetch(sha: str, path: str) -> str:
    with urllib.request.urlopen(RAW.format(sha=sha, path=path), timeout=60) as response:  # noqa: S310 - fixed https host
        return response.read().decode()


def parse_constants(text: str) -> dict[str, list[str]]:
    """`const NAME = ['a', ...other, 'b'];` and `export const NAME = 'a';` from a TypeScript file."""
    text = re.sub(r"(?m)//.*$", "", text)
    found: dict[str, list[str]] = {}
    for name, body in re.findall(r"(?:export\s+)?const\s+(\w+)\s*=\s*\[(.*?)\];", text, re.S):
        items: list[str] = []
        for m in re.finditer(r"\.\.\.(\w+)|'([^']+)'", body):
            items += found[m.group(1)] if m.group(1) else [m.group(2)]  # an unknown spread is a KeyError: stop
        found[name] = items
    for name, value in re.findall(r"export\s+const\s+(\w+)\s*=\s*'([^']+)';", text):
        found[name] = [value]
    return found


def snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def unique(items: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(items))


def load_names() -> dict[str, str]:
    """action string -> `p.Class.Attribute`, from the generated permissions module."""
    spec = importlib.util.spec_from_file_location("cfn_permissions", ROOT / "src" / "cfn_typed" / "permissions.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return {
        value: f"p.{cls}.{attr}"
        for cls, klass in vars(module).items() if isinstance(klass, type)
        for attr, value in vars(klass).items() if not attr.startswith("_") and isinstance(value, str)
    }


def json_grants(sha: str) -> list[tuple[str, str, list[str], dict[str, Entry]]]:
    out = []
    for cls, directory in JSON_SERVICES:
        spec = json.loads(fetch(sha, f"{directory}/grants.json"))
        for resource, body in spec["resources"].items():
            grants = {
                snake(name): (unique(g.get("actions", [])), unique(g.get("keyActions", [])), "any" if g.get("arnFormat") == "*" else "arn")
                for name, g in body["grants"].items()
            }
            out.append((cls, resource, [f"{directory}/grants.json"], grants))
    return out


def composed_grants(sha: str) -> list[tuple[str, str, list[str], dict[str, Entry]]]:
    out = []
    for entry in COMPOSED:
        constants: dict[str, list[str]] = {}
        for path in entry["files"]:
            constants.update(parse_constants(fetch(sha, path)))
        sources = "\n".join(fetch(sha, path) for path in entry["cite"])

        def resolve(items: list[str], entry: dict = entry, constants: dict = constants, sources: str = sources) -> tuple[str, ...]:
            resolved: list[str] = []
            for item in items:
                if ":" in item:  # a literal action: it must be written in the CDK file we cite for it
                    if f"'{item}'" not in sources:
                        sys.exit(f"{entry['service']}: {item!r} is not in {entry['cite']} at {sha}")
                    resolved.append(item)
                else:
                    if item not in constants:
                        sys.exit(f"{entry['service']}: constant {item} not found in {entry['files']} at {sha}")
                    resolved += constants[item]
            return unique(resolved)

        grants = {name: (resolve(acts), resolve(keys), shape) for name, (acts, keys, shape) in entry["grants"].items()}
        out.append((entry["service"], entry["resource"], entry["files"] + entry["cite"], grants))
    return out


def render(sha: str, services: list[tuple[str, str, list[str], dict[str, Entry]]], names: dict[str, str]) -> str:
    def ref(actions: tuple[str, ...], where: str) -> str:
        missing = [a for a in actions if a not in names]
        if missing:
            sys.exit(f"{where}: not a name in cfn_typed.permissions: {missing} (extend sync-cdk-permissions.py)")
        return "(" + ", ".join(names[a] for a in actions) + ("," if len(actions) == 1 else "") + ")"

    lines = [
        '"""The AWS CDK\'s permission sets, as data. Use them through `cfn_typed.grants`.',
        "",
        f"Source: https://github.com/aws/aws-cdk at commit {sha}",
        "(packages/aws-cdk-lib/...), licensed under the Apache License 2.0. See NOTICE and",
        "licenses/AWS-CDK-LICENSE.txt. Copyright Amazon.com, Inc. or its affiliates.",
        "",
        "Generated by scripts/sync-cdk-grants.py: do not edit.",
        '"""',
        "# fmt: off",
        "# ruff: noqa",
        "",
        "from typing import Final",
        "",
        "from cfn_typed import permissions as p",
        "from cfn_typed._grant import Grant",
        "",
        "__all__ = [" + ", ".join(f'"{c}"' for c in sorted({s[0] for s in services})) + "]",
    ]
    for service, resource, sources, grants in sorted(services, key=lambda s: (s[0], s[1])):
        lines += ["", "", f"class {service}:", f'    """From: {", ".join(sources)}"""', "", f"    class {resource}:"]
        for name, (actions, key_actions, shape) in grants.items():
            where = f"{service}.{resource}.{name}"
            parts = [f"actions={ref(actions, where)}"]
            if key_actions:
                parts.append(f"key_actions={ref(key_actions, where)}")
            if shape != "arn":
                parts.append(f'shape="{shape}"')
            lines.append(f"        {name}: Final = Grant({', '.join(parts)})")
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--sha", default=PINNED_SHA, help="aws-cdk commit to copy from")
    args = ap.parse_args()
    services = json_grants(args.sha) + composed_grants(args.sha)
    OUT.write_text(render(args.sha, services, load_names()))
    total = sum(len(g) for *_, g in services)
    print(f"wrote {OUT.relative_to(ROOT)}: {len(services)} resources, {total} grants, {OUT.stat().st_size} bytes (cdk {args.sha[:10]})")
    if args.sha != PINNED_SHA:
        print(f"update PINNED_SHA here and in sync-cdk-permissions.py to {args.sha} if you keep this result")


if __name__ == "__main__":
    main()
