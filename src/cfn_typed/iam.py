"""Check the IAM statements in a finished template against the action names `cfn_typed.permissions` carries.

    problems = find_iam_problems(template)   # [] when every statement looks right

Every policy document in `Resources` is read: a role's inline policies, `AWS::IAM::Policy`, managed policies, and resource
policies such as a queue, bucket or topic policy. Only the services in `cfn_typed.permissions` are known, so an action of
any other service is left alone.

- an action that is not in the service's list, or a wildcard that matches none of it (names are case-insensitive).
  The list comes from awacs, so an action AWS added since then is reported until `scripts/sync-permissions.py` is rerun;
- a `Resource` that refers (`Ref`, `GetAtt`, `Sub`, `Join`) to a resource of one of those services, when no action in the
  statement is from that service: a queue's ARN beside only `sns:` actions. The service of a resource type is its second
  part (`AWS::SQS::Queue` is `sqs`);
- S3 only: an object action (`s3:GetObject`) whose `Resource` is only the bucket ARN, which matches no object, or a bucket
  action (`s3:ListBucket`) whose `Resource` is only `{bucket arn}/...`, which matches no bucket.

Not checked: `NotAction`, actions or resources that are themselves intrinsics, and whether a policy grants too much.
"""

import difflib
import fnmatch
import re
from collections.abc import Iterator, Mapping
from typing import Any

from cfn_typed import permissions

_SUB_VAR = re.compile(r"\$\{([^}!][^}]*)\}")

S3_OBJECT = {"GetObject", "PutObject", "DeleteObject", "GetObjectVersion", "DeleteObjectVersion", "PutObjectAcl", "GetObjectAcl", "AbortMultipartUpload", "ListMultipartUploadParts", "RestoreObject"}
S3_BUCKET = {"ListBucket", "ListBucketVersions", "ListBucketMultipartUploads", "GetBucketLocation"}


def _known() -> dict[str, list[str]]:
    """Service prefix -> its action names, read from the `permissions` classes."""
    out: dict[str, list[str]] = {}
    for cls in vars(permissions).values():
        if isinstance(cls, type) and cls.__module__ == permissions.__name__:
            names = [v for k, v in vars(cls).items() if not k.startswith("_") and isinstance(v, str) and ":" in v]
            if names:
                out[names[0].split(":")[0].lower()] = [n.split(":", 1)[1] for n in names]
    return out


KNOWN = _known()


def _listed(value: Any) -> list[Any]:
    return value if isinstance(value, list) else [] if value is None else [value]


def _targets(expr: Any, resources: Mapping[str, Any]) -> Iterator[str]:
    """Logical IDs of the template's resources that `expr` refers to."""
    if isinstance(expr, list):
        for item in expr:
            yield from _targets(item, resources)
    elif isinstance(expr, Mapping):
        for key, value in expr.items():
            if key == "Ref" and value in resources:
                yield value
            elif key == "Fn::GetAtt":
                name = value.split(".")[0] if isinstance(value, str) else value[0] if isinstance(value, list) and value else None
                if isinstance(name, str) and name in resources:
                    yield name
            elif key == "Fn::Sub":
                text = value[0] if isinstance(value, list) and value else value
                for var in _SUB_VAR.findall(text) if isinstance(text, str) else []:
                    if var.split(".")[0] in resources:
                        yield var.split(".")[0]
                if isinstance(value, list) and len(value) == 2:
                    yield from _targets(value[1], resources)
            else:
                yield from _targets(value, resources)


def _level(expr: Any, resources: Mapping[str, Any]) -> str | None:
    """"bucket" or "object" for a `Resource` that names an S3 bucket's ARN or the objects under it, else None."""
    if isinstance(expr, str):
        if expr.startswith("arn:") and ":s3:::" in expr:
            return "object" if "/" in expr.split(":s3:::", 1)[1] else "bucket"
        named = [v.split(".")[0] for v in _SUB_VAR.findall(expr)]
        if not any(resources.get(n, {}).get("Type") == "AWS::S3::Bucket" for n in named):
            return None
        return "object" if "/" in _SUB_VAR.sub("", expr) else "bucket"
    buckets = [t for t in _targets(expr, resources) if resources[t].get("Type") == "AWS::S3::Bucket"]
    if not buckets or not isinstance(expr, Mapping):
        return None
    ((key, value),) = expr.items() if len(expr) == 1 else ((None, None),)
    if key == "Fn::Sub":
        text = value[0] if isinstance(value, list) and value else value
        return "object" if isinstance(text, str) and "/" in _SUB_VAR.sub("", text) else "bucket"
    if key == "Fn::Join" and isinstance(value, list) and len(value) == 2 and isinstance(value[1], list):
        return "object" if any(isinstance(p, str) and "/" in p for p in value[1]) else "bucket"
    return "bucket" if key == "Fn::GetAtt" else None


def _statement(stmt: Mapping[str, Any], path: str, resources: Mapping[str, Any], out: list[str]) -> None:
    actions = [a for a in _listed(stmt.get("Action")) if isinstance(a, str) and ":" in a]
    prefixes = {a.split(":")[0].lower() for a in actions}
    for action in actions:
        prefix, name = action.split(":", 1)
        names = KNOWN.get(prefix.lower())
        if names is None:
            continue
        if any(c in name for c in "*?"):
            if not any(fnmatch.fnmatchcase(n.lower(), name.lower()) for n in names):
                out.append(f"{path}.Action: {action!r} matches no {prefix.lower()} action")
        elif name.lower() not in {n.lower() for n in names}:
            close = difflib.get_close_matches(name, names, n=1)
            hint = f" (did you mean '{prefix.lower()}:{close[0]}'?)" if close else ""
            out.append(f"{path}.Action: {action!r} is not a known {prefix.lower()} action{hint}")
    wanted = _listed(stmt.get("Resource"))
    if "*" not in prefixes and not any(p.endswith("*") or p.startswith("*") for p in prefixes) and prefixes:
        for target in dict.fromkeys(t for r in wanted for t in _targets(r, resources)):
            kind = str(resources[target].get("Type", ""))
            service = kind.split("::")[1].lower() if kind.count("::") >= 2 else ""
            if service in KNOWN and service not in prefixes:
                out.append(f"{path}.Resource: refers to {target!r} ({kind}), but no action in the statement is a {service} action")
    if "s3" in prefixes:
        levels = {lv for r in wanted if (lv := _level(r, resources))}
        s3 = {a.split(":", 1)[1] for a in actions if a.split(":")[0].lower() == "s3"}
        if levels == {"bucket"} and s3 & S3_OBJECT:
            out.append(f"{path}.Resource: {sorted(s3 & S3_OBJECT)[0]!r} applies to objects, but Resource is only the bucket ARN: add '/*'")
        if levels == {"object"} and s3 & S3_BUCKET:
            out.append(f"{path}.Resource: {sorted(s3 & S3_BUCKET)[0]!r} applies to the bucket, but Resource is only objects: add the bucket ARN itself")


def _walk(node: Any, path: str, resources: Mapping[str, Any], out: list[str]) -> None:
    if isinstance(node, list):
        for i, item in enumerate(node):
            _walk(item, f"{path}[{i}]", resources, out)
    elif isinstance(node, Mapping):
        statements = node.get("Statement")
        if isinstance(statements, (list, Mapping)):
            for i, stmt in enumerate(_listed(statements)):
                if isinstance(stmt, Mapping) and "Effect" in stmt:
                    _statement(stmt, f"{path}.Statement[{i}]", resources, out)
        for key, value in node.items():
            _walk(value, f"{path}.{key}", resources, out)


def find_iam_problems(template: Mapping[str, Any]) -> list[str]:
    """Every IAM statement problem in `template`, one readable line each."""
    out: list[str] = []
    resources = template.get("Resources", {})
    _walk(resources, "Resources", {n: r for n, r in resources.items() if isinstance(r, Mapping)}, out)
    return list(dict.fromkeys(out))
