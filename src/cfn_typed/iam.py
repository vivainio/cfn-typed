"""Check the IAM statements in a finished template against the action names `cfn_typed.permissions` carries, and its condition keys.

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

- an `Effect` that is not `Allow` or `Deny`;
- a `Condition` operator that does not exist (`StringLik`; the `ForAllValues:` and `ForAnyValue:` prefixes and the `IfExists`
  suffix are understood);
- a condition key of one of those services that does not exist (`s3:prefx`), or that none of the statement's actions of that
  service supports (`s3:prefix` beside `s3:GetObject`: it is a `ListBucket` key). The keys come from AWS's Service
  Authorization Reference, see `scripts/sync-condition-keys.py`. Global `aws:` keys, keys of other services and keys
  that are themselves intrinsics are left alone.

Not checked: `NotAction`, actions or resources that are themselves intrinsics, the values of a condition, and whether a policy
grants too much.
"""

import difflib
import fnmatch
import functools
import re
from collections.abc import Iterator, Mapping
from typing import Any

from cfn_typed import permissions
from cfn_typed._condition_keys import CONDITION_KEYS

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


EFFECTS = ("Allow", "Deny")
OPERATORS = (
    *(f"String{op}" for op in ("Equals", "NotEquals", "EqualsIgnoreCase", "NotEqualsIgnoreCase", "Like", "NotLike")),
    *(f"{kind}{op}" for kind in ("Numeric", "Date") for op in ("Equals", "NotEquals", "LessThan", "LessThanEquals", "GreaterThan", "GreaterThanEquals")),
    "Bool", "BinaryEquals", "IpAddress", "NotIpAddress", "ArnEquals", "ArnLike", "ArnNotEquals", "ArnNotLike", "Null",
)  # fmt: skip
SET_PREFIXES = ("forallvalues:", "foranyvalue:")


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
    effect = stmt.get("Effect")
    if isinstance(effect, str) and effect not in EFFECTS:
        out.append(f"{path}.Effect: {effect!r} is not 'Allow' or 'Deny'")
    _condition(stmt, path, out)
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


def _operator(operator: str) -> str | None:
    """The problem with a condition operator, or None. Names are case-insensitive, as the rest of the checks treat them."""
    base = operator.lower()
    for prefix in SET_PREFIXES:
        base = base.removeprefix(prefix)
    if base.endswith("ifexists") and base != "nullifexists":  # `Null` has no IfExists form
        base = base.removesuffix("ifexists")
    if base in {o.lower() for o in OPERATORS}:
        return None
    close = difflib.get_close_matches(operator.split(":")[-1].removesuffix("IfExists"), OPERATORS, n=1)
    return f" (did you mean '{close[0]}'?)" if close else ""


_PLACEHOLDER = re.compile(r"<[^>]*>|\$\{[^}]*\}")


def _regex(name: str) -> re.Pattern[str]:
    """A condition key as a regex: `<key>` and `${TagKey}` match any name, the rest is literal and case-insensitive."""
    parts: list[str] = []
    last = 0
    for m in _PLACEHOLDER.finditer(name):
        parts += [re.escape(name[last : m.start()]), ".+"]
        last = m.end()
    return re.compile("".join([*parts, re.escape(name[last:])]) + "$", re.IGNORECASE)


@functools.cache
def _patterns(service: str) -> list[tuple[str, re.Pattern[str], int]]:
    """Every condition key of the service as (name, regex, index into its keys)."""
    return [(name, _regex(name), i) for i, name in enumerate(CONDITION_KEYS[service][0])]


def _supported(service: str, actions: list[str]) -> set[int] | None:
    """The indexes of the service's condition keys that any of the statement's actions of that service supports.

    None when the statement says something this cannot resolve (an action that is an intrinsic, `NotAction`) or has no
    action of the service at all, so there is nothing to compare with."""
    _, per_action = CONDITION_KEYS[service]
    known = KNOWN.get(service, [])
    matched: set[str] = set()
    for action in actions:
        if action == "*":
            matched |= set(known)
            continue
        prefix, _, name = action.partition(":")
        if fnmatch.fnmatchcase(service, prefix.lower()):
            matched |= {n for n in known if fnmatch.fnmatchcase(n.lower(), name.lower())}
    if not matched:
        return None
    return {i for n in matched for i in per_action.get(n, ())}


def _condition(stmt: Mapping[str, Any], path: str, out: list[str]) -> None:
    condition = stmt.get("Condition")
    if not isinstance(condition, Mapping):
        return
    raw = _listed(stmt.get("Action"))
    resolvable = "NotAction" not in stmt and all(isinstance(a, str) for a in raw)
    actions = [a for a in raw if isinstance(a, str)] if resolvable else []
    for operator, body in condition.items():
        if isinstance(operator, str) and (hint := _operator(operator)) is not None:
            out.append(f"{path}.Condition: {operator!r} is not a condition operator{hint}")
        if not isinstance(body, Mapping):
            continue
        for key in body:
            service = key.split(":")[0].lower() if isinstance(key, str) and ":" in key else ""
            if service not in CONDITION_KEYS:
                continue
            found = [(name, i) for name, rx, i in _patterns(service) if rx.match(key)]
            where = f"{path}.Condition.{operator}"
            if not found:
                names = [n for n, _, _ in _patterns(service)]
                close = difflib.get_close_matches(key, names, n=1, cutoff=0.7)
                hint = f" (did you mean {close[0]!r}?)" if close else ""
                out.append(f"{where}: {key!r} is not a known {service} condition key{hint}")
                continue
            supported = _supported(service, actions) if resolvable else None
            if supported is not None and not any(i in supported for _, i in found):
                _, per_action = CONDITION_KEYS[service]
                users = sorted(a for a, ix in per_action.items() if any(i in ix for _, i in found))
                shown = ", ".join(f"{service}:{a}" for a in users[:4]) + (", ..." if len(users) > 4 else "")
                out.append(f"{where}: {key!r} is not a condition key of any {service} action in the statement; it is for {shown}")


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
