"""SAM without SAM: expand `AWS::Serverless::*` resources into plain CloudFormation, in Python (docs/patterns/sam.md).

`expand(template)` returns a template with no `Transform` and no `Globals`: the function, its role, its event
source mappings, rules and routes are ordinary resources you can read, diff and check before deploying. It covers
a fixed subset of SAM (release pinned in `cfn-typegen.toml`) and raises `NotImplementedError` for anything else
instead of dropping it:

- `AWS::Serverless::Function` with an S3 `CodeUri`, `Policies`, `Environment`, the `SQS`, `Schedule` and `HttpApi`
  events, and `Globals.Function`;
- `AWS::Serverless::SimpleTable`.

Other resources pass through unchanged. Logical IDs are `{Function}`, `{Function}Role`, `{Function}{Event}`
(SQS), `{Function}{Event}Rule` and `{Function}{Event}Permission` (Schedule), and `{Function}Api...` (HttpApi,
one HTTP API per function).
"""

import json
from collections.abc import Mapping, Sequence
from typing import Any

from cfn_typed import Resources, Template, assume_role_policy, get_att, ref
from cfn_typed.policy import service

from cfn_typed_sumo.constructs import invoke_permission
from cfn_typed_sumo.http_api import http_api
from cfn_typed_sumo.types import dynamodb, events, iam, lambda_

BASIC_EXECUTION = "AWSLambdaBasicExecutionRole"
SQS_EXECUTION = "AWSLambdaSQSQueueExecutionRole"

# Function properties that mean the same thing on AWS::Lambda::Function
_PASS_THROUGH = (
    "Architectures", "Description", "EphemeralStorage", "FunctionName", "KmsKeyArn", "Layers", "MemorySize",
    "ReservedConcurrentExecutions", "Runtime", "Timeout", "VpcConfig", "CodeSigningConfigArn",
)
_HANDLED = {"Handler", "CodeUri", "Policies", "Environment", "Events", "Tags", *_PASS_THROUGH}


def _unsupported(what: str, name: str, keys: Sequence[str]) -> NotImplementedError:
    return NotImplementedError(f"{name}: {what} not supported by expand: {', '.join(sorted(keys))}")


def _managed_arn(policy: str) -> Any:
    if policy.startswith("arn:"):
        return policy
    return {"Fn::Sub": f"arn:${{AWS::Partition}}:iam::aws:policy/service-role/{policy}"} if policy.startswith("AWSLambda") \
        else {"Fn::Sub": f"arn:${{AWS::Partition}}:iam::aws:policy/{policy}"}


def _tag_list(tags: Mapping[str, Any]) -> list[Any]:
    return [{"Key": k, "Value": v} for k, v in tags.items()]


def _code(name: str, uri: Any) -> Any:
    if isinstance(uri, str) and uri.startswith("s3://"):
        bucket, _, key = uri.removeprefix("s3://").partition("/")
        return {"S3Bucket": bucket, "S3Key": key}
    if isinstance(uri, Mapping) and "Bucket" in uri and "Key" in uri:
        return {"S3Bucket": uri["Bucket"], "S3Key": uri["Key"], **({"S3ObjectVersion": uri["Version"]} if "Version" in uri else {})}
    raise NotImplementedError(f"{name}: CodeUri must be an s3://bucket/key URI or a Bucket/Key mapping (expand does not package code), got {uri!r}")


def merged_globals(props: Mapping[str, Any], defaults: Mapping[str, Any], ignore: Sequence[str]) -> dict[str, Any]:
    """`props` over the `Globals.Function` `defaults`: scalars are replaced, `Environment.Variables` and `Tags` are merged."""
    out: dict[str, Any] = {k: v for k, v in defaults.items() if k not in ignore}
    for key, value in props.items():
        if key == "Environment" and "Environment" in out:
            out[key] = {"Variables": {**out[key].get("Variables", {}), **value.get("Variables", {})}}
        elif key == "Tags" and "Tags" in out:
            out[key] = {**out[key], **value}
        else:
            out[key] = value
    return out


def _function(name: str, res: Mapping[str, Any], defaults: Mapping[str, Any]) -> Resources:
    ignore = res.get("IgnoreGlobals", [])
    if res.get("Connectors"):
        raise _unsupported("resource key", name, ["Connectors"])
    props = merged_globals(res.get("Properties", {}), defaults, [ignore] if isinstance(ignore, str) else ignore)
    if extra := set(props) - _HANDLED:
        raise _unsupported("properties", name, list(extra))
    event_map: Mapping[str, Any] = props.get("Events", {})
    role = f"{name}Role"

    managed: list[Any] = [_managed_arn(BASIC_EXECUTION)]
    inline: list[Any] = []
    for policy in ([props["Policies"]] if isinstance(props.get("Policies"), (str, Mapping)) else props.get("Policies", [])):
        if isinstance(policy, str):
            managed.append(_managed_arn(policy))
        elif "Statement" in policy:
            inline.append({"PolicyName": f"{role}Policy{len(inline) + 1}", "PolicyDocument": {"Version": "2012-10-17", **policy}})
        else:
            raise _unsupported("policy", name, ["policy templates (use managed policy names or statements)"])
    if any(e.get("Type") == "SQS" for e in event_map.values()):
        managed.append(_managed_arn(SQS_EXECUTION))
    managed = [json.loads(m) for m in dict.fromkeys(json.dumps(m, sort_keys=True) for m in managed)]  # named twice, attached once

    role_props: Any = {
        "AssumeRolePolicyDocument": assume_role_policy(service("lambda.amazonaws.com")),
        "ManagedPolicyArns": managed,
    }
    if inline:
        role_props["Policies"] = inline
    fn_props: Any = {"Code": _code(name, props.get("CodeUri")), "Handler": props.get("Handler"), "Role": get_att(role, "Arn")}
    fn_props = {k: v for k, v in fn_props.items() if v is not None}
    fn_props.update({k: props[k] for k in _PASS_THROUGH if k in props})
    if "Environment" in props:
        fn_props["Environment"] = {"Variables": props["Environment"].get("Variables", {})}
    if "Tags" in props:
        fn_props["Tags"] = role_props["Tags"] = _tag_list(props["Tags"])

    out: Resources = {role: iam.role(**role_props), name: lambda_.function(**fn_props)}
    routes: list[str] = []
    for event_name, event in event_map.items():
        out |= _event(name, event_name, event, routes)
    if routes:
        out |= http_api(f"{name}", function=name, routes=routes).resources
    for key in ("Condition", "DependsOn", "DeletionPolicy", "UpdateReplacePolicy", "Metadata"):
        if key in res:
            out[name][key] = res[key]
    return out


def _event(function: str, event_name: str, event: Mapping[str, Any], routes: list[str]) -> Resources:
    kind, props = event.get("Type"), event.get("Properties", {})
    logical = f"{function}{event_name}"
    match kind:
        case "SQS":
            if extra := set(props) - {"Queue", "BatchSize", "MaximumBatchingWindowInSeconds", "Enabled"}:
                raise _unsupported(f"SQS event {event_name!r} properties", function, list(extra))
            mapping: Any = {"EventSourceArn": props["Queue"], "FunctionName": ref(function)}
            for src, dst in (("BatchSize", "BatchSize"), ("MaximumBatchingWindowInSeconds", "MaximumBatchingWindowInSeconds"), ("Enabled", "Enabled")):
                if src in props:
                    mapping[dst] = props[src]
            return {logical: lambda_.event_source_mapping(**mapping)}
        case "Schedule":
            if extra := set(props) - {"Schedule", "Enabled"}:
                raise _unsupported(f"Schedule event {event_name!r} properties", function, list(extra))
            rule: Any = {"ScheduleExpression": props["Schedule"], "Targets": [{"Arn": get_att(function, "Arn"), "Id": f"{logical}LambdaTarget"}]}
            if "Enabled" in props:  # as SAM: no `Enabled`, no `State`
                rule["State"] = "ENABLED" if props["Enabled"] else "DISABLED"
            return {logical: events.rule(**rule), f"{logical}Permission": invoke_permission(function, "events.amazonaws.com", get_att(logical, "Arn"))}
        case "HttpApi":
            if "ApiId" in props or props.get("Auth"):
                raise _unsupported(f"HttpApi event {event_name!r} properties", function, ["ApiId", "Auth"])
            routes.append(f"{props.get('Method', 'ANY').upper()} {props.get('Path', '/{proxy+}')}")
            return {}
    raise NotImplementedError(f"{function}: event {event_name!r} of type {kind!r} not supported by expand (SQS, Schedule, HttpApi)")


def _table(name: str, res: Mapping[str, Any]) -> Resources:
    props = res.get("Properties", {})
    if extra := set(props) - {"PrimaryKey", "ProvisionedThroughput", "TableName", "Tags"}:
        raise _unsupported("properties", name, list(extra))
    key = props.get("PrimaryKey", {"Name": "id", "Type": "String"})
    table: Any = {
        "AttributeDefinitions": [{"AttributeName": key["Name"], "AttributeType": {"String": "S", "Number": "N", "Binary": "B"}[key["Type"]]}],
        "KeySchema": [{"AttributeName": key["Name"], "KeyType": "HASH"}],
    }
    if "ProvisionedThroughput" in props:
        throughput = props["ProvisionedThroughput"]
        table["ProvisionedThroughput"] = {"ReadCapacityUnits": throughput["ReadCapacityUnits"], "WriteCapacityUnits": throughput["WriteCapacityUnits"]}
    else:
        table["BillingMode"] = "PAY_PER_REQUEST"
    if "TableName" in props:
        table["TableName"] = props["TableName"]
    if "Tags" in props:
        table["Tags"] = _tag_list(props["Tags"])
    return {name: dynamodb.table(**table)}


def expand(template: Template) -> Template:
    """`template` with every `AWS::Serverless::*` resource replaced by the plain resources it stands for.

    The result has no `Transform` and no `Globals`. See the module docstring for what is covered.
    """
    defaults = template.get("Globals", {}).get("Function", {})
    if other := set(template.get("Globals", {})) - {"Function"}:
        raise NotImplementedError(f"Globals not supported by expand: {', '.join(sorted(other))}")
    resources: Resources = {}
    for name, res in template["Resources"].items():
        match res["Type"]:
            case "AWS::Serverless::Function":
                resources |= _function(name, res, defaults)
            case "AWS::Serverless::SimpleTable":
                resources |= _table(name, res)
            case t if t.startswith("AWS::Serverless::"):
                raise NotImplementedError(f"{name}: {t} not supported by expand")
            case _:
                resources[name] = res
    out: Template = {k: v for k, v in template.items() if k not in ("Transform", "Globals", "Resources")}  # ty: ignore[invalid-assignment]
    transform = template.get("Transform")
    if transform not in (None, "AWS::Serverless-2016-10-31") and transform != ["AWS::Serverless-2016-10-31"]:
        out["Transform"] = transform  # some other macro is still in use
    out["Resources"] = resources
    return out
