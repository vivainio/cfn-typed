"""Review what a deploy would do to a stack that is already running, before it does it.

    changes = plan("ledger-dev", template)            # a change set, created and read, never executed
    problems = find_change_problems(changes)          # a stateful resource replaced or removed: [] when there is none
    print(format_changes(changes))

    differences = find_deployed_differences(template, get_deployed("ledger-dev"))   # the rendered template against the live one

`plan` makes a change set with the `aws` command line (so it uses your credentials, profile and region), reads it, and deletes
it again unless `keep=True`. It never executes it. A resource marked `Replacement` is a new physical resource: for a table,
a bucket, a key or a distribution that means the data or the identity is gone, and the change set is the only place that says so
before it happens. `find_change_problems` fails on exactly those.

`find_retention_problems` is the other half, in the template: a stateful resource with no `DeletionPolicy` and
`UpdateReplacePolicy` that keeps it. It is an opinion, so it is a rule you add (`rules=[find_retention_problems]`), not part of
`find_all_problems`.
"""

import json
import os
import subprocess
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

STATEFUL = frozenset({
    "AWS::Backup::BackupVault",
    "AWS::CloudFront::Distribution",
    "AWS::Cognito::UserPool",
    "AWS::DocDB::DBCluster",
    "AWS::DynamoDB::GlobalTable",
    "AWS::DynamoDB::Table",
    "AWS::EC2::Volume",
    "AWS::ECR::Repository",
    "AWS::EFS::FileSystem",
    "AWS::ElastiCache::ReplicationGroup",
    "AWS::Elasticsearch::Domain",
    "AWS::KMS::Key",
    "AWS::Kinesis::Stream",
    "AWS::Logs::LogGroup",
    "AWS::MSK::Cluster",
    "AWS::Neptune::DBCluster",
    "AWS::OpenSearchService::Domain",
    "AWS::RDS::DBCluster",
    "AWS::RDS::DBInstance",
    "AWS::Route53::HostedZone",
    "AWS::S3::Bucket",
    "AWS::SNS::Topic",
    "AWS::SQS::Queue",
    "AWS::SecretsManager::Secret",
})
"""The types whose replacement or removal loses data or an identity others depend on. Pass your own set to the functions below."""

_KEEPS = {"Retain", "RetainExceptOnCreate", "Snapshot"}
_NO_CHANGES = ("didn't contain changes", "no updates are to be performed")


@dataclass(frozen=True)
class Change:
    """One line of a change set."""

    logical_id: str
    type: str
    action: str  # Add, Modify, Remove, Import, Dynamic
    replacement: str = "False"  # True, False or Conditional
    physical_id: str = ""
    details: tuple[str, ...] = ()  # what changes, e.g. "Properties.BucketName (recreates)"


def parse_changes(described: Mapping[str, Any]) -> list[Change]:
    """The `Changes` of the output of `aws cloudformation describe-change-set`."""
    out: list[Change] = []
    for entry in described.get("Changes") or []:
        change = entry.get("ResourceChange") or {}
        details = tuple(
            f"{(d.get('Target') or {}).get('Attribute', '')}.{(d.get('Target') or {}).get('Name', '')}".strip(".")
            + (f" ({d['Target']['RequiresRecreation'].lower()})" if (d.get("Target") or {}).get("RequiresRecreation") not in (None, "Never") else "")
            for d in change.get("Details") or []
        )
        out.append(Change(
            change.get("LogicalResourceId", ""), change.get("ResourceType", ""), change.get("Action", ""),
            str(change.get("Replacement", "False")), change.get("PhysicalResourceId", ""), details,
        ))
    return out


def find_change_problems(changes: Sequence[Change], *, stateful: frozenset[str] | set[str] = STATEFUL, strict: bool = False) -> list[str]:
    """The changes that lose something, one readable line each: a stateful resource that is replaced (or may be) or removed. `strict=True` also reports any replacement and any removal."""
    out: list[str] = []
    for c in changes:
        loses = c.type in stateful
        why = f" ({', '.join(c.details)})" if c.details else ""
        if c.action == "Remove" and (loses or strict):
            out.append(f"{c.logical_id} ({c.type}) would be removed")
        elif c.replacement == "True" and (loses or strict):
            out.append(f"{c.logical_id} ({c.type}) would be replaced{why}")
        elif c.replacement == "Conditional" and (loses or strict):
            out.append(f"{c.logical_id} ({c.type}) may be replaced{why}")
    return out


def format_changes(changes: Sequence[Change]) -> str:
    """The changes as a table, one line each; `no changes` when the list is empty."""
    if not changes:
        return "no changes"
    rows = [(c.logical_id, c.type, c.action + (" (replacement)" if c.replacement == "True" else " (maybe replacement)" if c.replacement == "Conditional" else ""), ", ".join(c.details)) for c in changes]
    widths = [max(len(r[i]) for r in rows) for i in range(3)]
    return "\n".join(f"{a:<{widths[0]}}  {b:<{widths[1]}}  {c:<{widths[2]}}  {d}".rstrip() for a, b, c, d in rows)


def find_retention_problems(template: Mapping[str, Any], *, stateful: frozenset[str] | set[str] = STATEFUL) -> list[str]:
    """Stateful resources that a delete or a replacement would destroy: no `DeletionPolicy`, or no `UpdateReplacePolicy`, of `Retain` (or `Snapshot`). A rule for `rules=`; an opinion, since a throwaway stack wants the opposite."""
    out: list[str] = []
    for logical, resource in (template.get("Resources") or {}).items():
        if not isinstance(resource, Mapping) or resource.get("Type") not in stateful:
            continue
        for key in ("DeletionPolicy", "UpdateReplacePolicy"):
            if resource.get(key) not in _KEEPS:
                out.append(f"Resources.{logical} ({resource['Type']}): {key} is {resource.get(key, 'not set')}, not Retain or Snapshot")
    return out


type Runner = Callable[[Sequence[str]], Any]
"""Runs the `aws` command line with these arguments and returns its JSON output (None when it prints none)."""


def aws_runner(*, profile: str | None = None, region: str | None = None) -> Runner:
    """A `Runner` that calls `aws`, with `--profile` and `--region` when given. A failing command raises `RuntimeError` with what `aws` said."""
    extra = [*(["--profile", profile] if profile else []), *(["--region", region] if region else [])]

    def run(args: Sequence[str]) -> Any:
        done = subprocess.run(["aws", *args, *extra, "--output", "json"], capture_output=True, text=True)
        if done.returncode != 0:
            raise RuntimeError(f"aws {' '.join(args[:2])} failed: {done.stderr.strip() or done.stdout.strip()}")
        return json.loads(done.stdout) if done.stdout.strip() else None

    return run


def plan(
    stack_name: str,
    template: Mapping[str, Any],
    *,
    runner: Runner | None = None,
    capabilities: Sequence[str] = ("CAPABILITY_IAM", "CAPABILITY_NAMED_IAM"),
    keep: bool = False,
    poll: float = 2.0,
    timeout: float = 600,
    resources_to_import: Sequence[Mapping[str, Any]] | None = None,
    change_set_name: str | None = None,
) -> list[Change]:
    """Create a change set of `template` against the running `stack_name`, read it, delete it (unless `keep`) and return its changes. An empty list means a deploy changes nothing. The template goes inline, so it must be under 51,200 bytes.

    `resources_to_import` (see `cfn_typed.adopt`) makes it an IMPORT change set, which brings existing resources into the stack and changes nothing else. `change_set_name` names it; a change set you will execute is one you keep.
    """
    run = runner or aws_runner()
    body = json.dumps(template, separators=(",", ":"))
    if len(body.encode()) > 51200:
        raise ValueError(f"the template is {len(body.encode())} bytes; an inline change set takes 51,200. Upload it to S3 and use `aws cloudformation deploy --no-execute-changeset`")
    name = change_set_name or f"cfn-typed-{int(time.time())}"
    fd, path = tempfile.mkstemp(suffix=".json")
    fd2, path2 = tempfile.mkstemp(suffix=".json")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(body)
        with os.fdopen(fd2, "w") as f:
            json.dump(list(resources_to_import or []), f)
        run(["cloudformation", "create-change-set", "--stack-name", stack_name, "--change-set-name", name,
             "--change-set-type", "IMPORT" if resources_to_import else "UPDATE", "--template-body", f"file://{path}",
             *(["--resources-to-import", f"file://{path2}"] if resources_to_import else []),
             *(["--capabilities", *capabilities] if capabilities else [])])
    finally:
        os.unlink(path)
        os.unlink(path2)
    try:
        deadline = time.monotonic() + timeout
        while True:
            described = run(["cloudformation", "describe-change-set", "--stack-name", stack_name, "--change-set-name", name])
            status = described.get("Status")
            if status == "CREATE_COMPLETE":
                return parse_changes(described)
            if status == "FAILED":
                reason = str(described.get("StatusReason", ""))
                if any(text in reason.lower() for text in _NO_CHANGES):
                    return []
                raise RuntimeError(f"the change set failed: {reason}")
            if time.monotonic() > deadline:
                raise TimeoutError(f"the change set was still {status} after {timeout:.0f} seconds")
            time.sleep(poll)
    finally:
        if not keep:
            try:
                run(["cloudformation", "delete-change-set", "--stack-name", stack_name, "--change-set-name", name])
            except RuntimeError:
                pass


def get_deployed(stack_name: str, *, stage: str = "Original", runner: Runner | None = None) -> dict[str, Any]:
    """The template of the running stack. `stage` is `Original`, or `Processed` after the transforms (SAM) have run."""
    result = (runner or aws_runner())(["cloudformation", "get-template", "--stack-name", stack_name, "--template-stage", stage])
    body = result["TemplateBody"]
    if isinstance(body, Mapping):
        return dict(body)
    from cfn_typed.cli import parse_template

    return parse_template(body)


def template_differences(rendered: Any, deployed: Any, path: str = "") -> list[str]:
    """Where two templates differ, one line each, with the path in the template. Key order does not matter; list order does."""
    here = path or "(template)"
    if isinstance(rendered, Mapping) and isinstance(deployed, Mapping):
        out: list[str] = []
        for key in dict.fromkeys([*rendered, *deployed]):
            where = f"{path}.{key}" if path else str(key)
            if key not in deployed:
                out.append(f"{where}: only in the rendered template")
            elif key not in rendered:
                out.append(f"{where}: only in the deployed template")
            else:
                out += template_differences(rendered[key], deployed[key], where)
        return out
    if isinstance(rendered, list) and isinstance(deployed, list):
        out = [] if len(rendered) == len(deployed) else [f"{here}: {len(rendered)} items rendered, {len(deployed)} deployed"]
        for i, (a, b) in enumerate(zip(rendered, deployed)):
            out += template_differences(a, b, f"{path}[{i}]")
        return out
    return [] if rendered == deployed and type(rendered) is type(deployed) else [f"{here}: rendered {json.dumps(rendered)}, deployed {json.dumps(deployed)}"]


def find_deployed_differences(rendered: Mapping[str, Any], deployed: Mapping[str, Any]) -> list[str]:
    """How the rendered template differs from the deployed one: the first thing to check after an ejection. `[]` means a deploy of it has nothing to change. `Metadata` and the `Description` of the deployed template are compared too."""
    return template_differences(dict(rendered), dict(deployed))


__all__: Sequence[str] = [
    "STATEFUL", "Change", "aws_runner", "find_change_problems", "find_deployed_differences", "find_retention_problems", "format_changes",
    "get_deployed", "parse_changes", "plan", "template_differences",
]
