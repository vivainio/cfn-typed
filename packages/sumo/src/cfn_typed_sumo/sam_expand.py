"""SAM without SAM: expand `AWS::Serverless::*` resources into plain CloudFormation, in Python (docs/patterns/sam.md).

`expand(template)` returns a template with no `Transform` and no `Globals`: the function, its role, its event
source mappings, rules and routes are ordinary resources you can read, diff and check before deploying. It covers
a fixed subset of SAM (release pinned in `cfn-typegen.toml`) and raises `NotImplementedError` for anything else
instead of dropping it:

- `AWS::Serverless::Function` with an S3 `CodeUri`, `Policies`, `Environment`, the `SQS`, `Kinesis`, `DynamoDB`, `SNS`,
  `Schedule`, `EventBridgeRule` and `HttpApi` events, and `Globals.Function`;
- `AWS::Serverless::SimpleTable`;
- `AWS::Serverless::Connector` between a function in the template and an SQS queue, SNS topic, S3 bucket, DynamoDB
  table, `SimpleTable` or function in it, with `Read` and `Write`.

Other resources pass through unchanged. Logical IDs are the ones SAM makes: `{Function}`, `{Function}Role`,
`{Function}{Event}` (the mapping, rule or subscription), `{Function}{Event}Permission`, `{Connector}Policy`. The
exception is HttpApi, which gets `{Function}Api...` (one HTTP API per function) instead of SAM's shared one.
"""

import json
from collections.abc import Mapping, Sequence
from typing import Any

from cfn_typed import Resources, Template, assume_role_policy, get_att, ref
from cfn_typed.policy import service

from cfn_typed_sumo.constructs import invoke_permission
from cfn_typed_sumo.http_api import http_api
from cfn_typed_sumo.types import dynamodb, events, iam, lambda_, sns

BASIC_EXECUTION = "AWSLambdaBasicExecutionRole"
# Events that poll a source need the function's role to read from it
EXECUTION_POLICY = {
    "SQS": "AWSLambdaSQSQueueExecutionRole",
    "Kinesis": "AWSLambdaKinesisExecutionRole",
    "DynamoDB": "AWSLambdaDynamoDBExecutionRole",
}

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
    managed += [_managed_arn(EXECUTION_POLICY[t]) for e in event_map.values() if (t := e.get("Type")) in EXECUTION_POLICY]
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
        case "SQS" | "Kinesis" | "DynamoDB":
            source = {"SQS": "Queue"}.get(kind, "Stream")
            allowed = {source, "BatchSize", "MaximumBatchingWindowInSeconds", "Enabled", *({"FilterCriteria"} if kind == "SQS" else {"StartingPosition", "FilterCriteria"})}
            if extra := set(props) - allowed:
                raise _unsupported(f"{kind} event {event_name!r} properties", function, list(extra))
            if source not in props:
                raise NotImplementedError(f"{function}: {kind} event {event_name!r} needs {source}")
            mapping: Any = {"EventSourceArn": props[source], "FunctionName": ref(function)}
            mapping.update({k: v for k, v in props.items() if k != source})
            return {logical: lambda_.event_source_mapping(**mapping)}
        case "SNS":
            if extra := set(props) - {"Topic"}:
                raise _unsupported(f"SNS event {event_name!r} properties", function, list(extra))
            return {
                logical: sns.subscription(TopicArn=props["Topic"], Protocol="lambda", Endpoint=get_att(function, "Arn")),
                f"{logical}Permission": invoke_permission(function, "sns.amazonaws.com", props["Topic"]),
            }
        case "EventBridgeRule":
            if extra := set(props) - {"Pattern"}:
                raise _unsupported(f"EventBridgeRule event {event_name!r} properties", function, list(extra))
            return {
                logical: events.rule(EventPattern=props["Pattern"], Targets=[{"Arn": get_att(function, "Arn"), "Id": f"{logical}LambdaTarget"}]),
                f"{logical}Permission": invoke_permission(function, "events.amazonaws.com", get_att(logical, "Arn")),
            }
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
    raise NotImplementedError(f"{function}: event {event_name!r} of type {kind!r} not supported by expand (SQS, Kinesis, DynamoDB, SNS, Schedule, EventBridgeRule, HttpApi)")


# What `Read` and `Write` allow on each kind of destination, and which resources the statement covers: "arn",
# "ref" (the topic's Ref is its ARN), "arn/*" and "arn/index/*" (the objects of a bucket, the indexes of a table).
_DYNAMO = {
    "Read": ("arn+index", ["dynamodb:GetItem", "dynamodb:Query", "dynamodb:Scan", "dynamodb:BatchGetItem", "dynamodb:ConditionCheckItem", "dynamodb:PartiQLSelect"]),
    "Write": ("arn+index", ["dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem", "dynamodb:BatchWriteItem", "dynamodb:PartiQLDelete", "dynamodb:PartiQLInsert", "dynamodb:PartiQLUpdate"]),
}
_LAMBDA = {"Write": ("arn", ["lambda:InvokeAsync", "lambda:InvokeFunction"])}
CONNECTOR_ACCESS: dict[str, dict[str, tuple[str, list[str]]]] = {
    "AWS::SQS::Queue": {
        "Read": ("arn", ["sqs:ReceiveMessage", "sqs:GetQueueAttributes"]),
        "Write": ("arn", ["sqs:DeleteMessage", "sqs:SendMessage", "sqs:ChangeMessageVisibility", "sqs:PurgeQueue"]),
    },
    "AWS::SNS::Topic": {"Write": ("ref", ["sns:Publish"])},
    "AWS::S3::Bucket": {
        "Read": ("arn+objects", ["s3:GetObject", "s3:GetObjectAcl", "s3:GetObjectLegalHold", "s3:GetObjectRetention", "s3:GetObjectTorrent", "s3:GetObjectVersion", "s3:GetObjectVersionAcl", "s3:GetObjectVersionForReplication", "s3:GetObjectVersionTorrent", "s3:ListBucket", "s3:ListBucketMultipartUploads", "s3:ListBucketVersions", "s3:ListMultipartUploadParts"]),
        "Write": ("arn+objects", ["s3:AbortMultipartUpload", "s3:DeleteObject", "s3:DeleteObjectVersion", "s3:PutObject", "s3:PutObjectLegalHold", "s3:PutObjectRetention", "s3:RestoreObject"]),
    },
    "AWS::DynamoDB::Table": _DYNAMO,
    "AWS::Serverless::SimpleTable": _DYNAMO,
    "AWS::Lambda::Function": _LAMBDA,
    "AWS::Serverless::Function": _LAMBDA,
}


def _resources_for(kind: str, dest: str) -> list[Any]:
    arn = get_att(dest, "Arn")
    suffix = {"arn+index": "/index/*", "arn+objects": "/*"}
    return [ref(dest)] if kind == "ref" else [arn] if kind == "arn" else [arn, {"Fn::Sub": ["${DestinationArn}" + suffix[kind], {"DestinationArn": arn}]}]


def _connector(name: str, res: Mapping[str, Any], resources: Mapping[str, Any]) -> Resources:
    props = res.get("Properties", {})
    if extra := set(props) - {"Source", "Destination", "Permissions"}:
        raise _unsupported("properties", name, list(extra))
    source = props["Source"]
    if set(source) != {"Id"} or resources.get(source["Id"], {}).get("Type") != "AWS::Serverless::Function":
        raise _unsupported("Source", name, ["only {Id: <AWS::Serverless::Function in this template>}"])
    destinations = props["Destination"] if isinstance(props["Destination"], list) else [props["Destination"]]
    out: Resources = {}
    for i, dest in enumerate(destinations):
        kind = resources.get(dest.get("Id"), {}).get("Type") if set(dest) == {"Id"} else None
        if kind is None:
            raise _unsupported("Destination", name, ["only {Id: <resource in this template>}"])
        access = CONNECTOR_ACCESS.get(kind)
        if access is None or (missing := [p for p in props["Permissions"] if p not in access]):
            raise NotImplementedError(f"{name}: {', '.join(props['Permissions'])} on {kind} not supported by expand")
        statements = [{"Effect": "Allow", "Action": access[p][1], "Resource": _resources_for(access[p][0], dest["Id"])} for p in props["Permissions"]]
        policy_id = f"{name}Policy" if len(destinations) == 1 else f"{name}PolicyDestination{i}"
        out[policy_id] = iam.managed_policy(
            PolicyDocument={"Version": "2012-10-17", "Statement": statements}, Roles=[ref(f"{source['Id']}Role")],
        )
    return out


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
            case "AWS::Serverless::Connector":
                resources |= _connector(name, res, template["Resources"])
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
