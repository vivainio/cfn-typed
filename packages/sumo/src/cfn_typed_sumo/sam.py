"""AWS SAM on top of the generated `cfn_typed_sumo.types.serverless` types (docs/patterns/sam.md).

The `AWS::Serverless::*` resources (`serverless.function`, `serverless.simple_table`, ...) come from the SAM
release pinned in `cfn-typegen.toml`. This module adds what a SAM template needs around them: the `Transform`
header, `Globals`, and typed builders for the event sources that are easy to get wrong inline.
"""

from collections.abc import Mapping, Sequence
from typing import Any, Literal

from cfn_typed_sumo.types import serverless

from cfn_typed import AnyStatement, Expr, Resources, Template, policy_document

SAM_TRANSFORM = "AWS::Serverless-2016-10-31"


def template(
    resources: Resources,
    *,
    description: str | None = None,
    function_globals: serverless.FunctionProps | Mapping[str, Any] | None = None,
    globals: Mapping[str, Mapping[str, Any]] | None = None,
) -> Template:
    """A SAM template: `Transform` set, `Globals` when given, then the resources.

    `function_globals` is shorthand for `globals={"Function": ...}`. SAM merges `Globals` into every resource of
    that kind, so put Runtime, Timeout, Environment and Tags here once instead of on each function.
    """
    out: Template = {"AWSTemplateFormatVersion": "2010-09-09", "Transform": SAM_TRANSFORM, "Resources": resources}
    if description:
        out["Description"] = description
    merged: dict[str, Any] = {k: dict(v) for k, v in (globals or {}).items()}
    if function_globals:
        merged["Function"] = {**merged.get("Function", {}), **function_globals}
    if merged:
        out["Globals"] = merged
    return out


def sqs_event(queue_arn: Expr[Any], *, batch_size: int = 10, max_batching_window: int | None = None) -> serverless.FunctionSQSEvent:
    """An `SQS` event: SAM creates the event source mapping and grants the function read access to the queue."""
    props: serverless.FunctionSQSEventProperties = {"Queue": queue_arn, "BatchSize": batch_size}
    if max_batching_window is not None:
        props["MaximumBatchingWindowInSeconds"] = max_batching_window
    return {"Type": "SQS", "Properties": props}


def http_api_event(path: str, method: str = "ANY", *, api_id: Expr[str] | None = None) -> serverless.FunctionHttpApiEvent:
    """An `HttpApi` event: a route on the implicit HTTP API, or on `api_id` when given."""
    props: serverless.FunctionHttpApiEventProperties = {"Path": path, "Method": method}
    if api_id is not None:
        props["ApiId"] = api_id
    return {"Type": "HttpApi", "Properties": props}


def schedule_event(expression: str, *, enabled: bool = True) -> serverless.FunctionScheduleEvent:
    """A `Schedule` event, `"rate(5 minutes)"` or `"cron(0 8 * * ? *)"`: SAM creates the rule and the invoke permission."""
    props: serverless.FunctionEventsScheduleProperties = {"Schedule": expression, "Enabled": enabled}
    return {"Type": "Schedule", "Properties": props}


def function(
    *,
    handler: str,
    code_uri: str | serverless.FunctionCodeUri,
    events: Mapping[str, Any] | None = None,
    environment: Mapping[str, Expr[str]] | None = None,
    statements: Sequence[AnyStatement] = (),
    managed_policies: Sequence[str] = (),
    memory: int | None = None,
    timeout: int | None = None,
    runtime: str | None = None,
) -> serverless.Function:
    """`AWS::Serverless::Function` with the arguments written the way the rest of the patterns write them.

    `statements` become one inline policy (the same statements as [grants](../grants.md)) and `managed_policies` are
    policy names or ARNs, both under SAM's `Policies`. Leave `runtime`, `memory` and `timeout` out to take them from
    `template(function_globals=...)`; SAM does the merge when it deploys.
    """
    props: serverless.FunctionProps = {"Handler": handler, "CodeUri": code_uri}
    if events:
        props["Events"] = events
    if environment:
        props["Environment"] = {"Variables": environment}
    policies: list[Any] = [*managed_policies, *([policy_document(statements)] if statements else [])]
    if policies:
        props["Policies"] = policies
    if memory is not None:
        props["MemorySize"] = memory
    if timeout is not None:
        props["Timeout"] = timeout
    if runtime is not None:
        props["Runtime"] = runtime
    return serverless.function(**props)


def table(key: str, key_type: Literal["String", "Number", "Binary"] = "String") -> serverless.SimpleTable:
    """`AWS::Serverless::SimpleTable`: a DynamoDB table with one partition key, on-demand billing by SAM's default."""
    return serverless.simple_table(PrimaryKey={"Name": key, "Type": key_type})


def connect(
    name: str, source: str, destination: str | Sequence[str], permissions: Sequence[Literal["Read", "Write"]] = ("Read",),
) -> Resources:
    """`AWS::Serverless::Connector` `{name}Connector`: grant `source` access to `destination` without writing IAM.

    `source` and `destination` are logical IDs of resources in this template. SAM writes the least-privilege policy
    for the pair, which is the part of SAM that replaces a hand-written role statement.
    """
    ids = [destination] if isinstance(destination, str) else list(destination)
    refs: list[Expr[serverless.ConnectorResourceReference]] = [{"Id": d} for d in ids]
    return {f"{name}Connector": serverless.connector(
        Source={"Id": source}, Destination=refs[0] if len(refs) == 1 else refs, Permissions=list(permissions),
    )}


__all__ = ["SAM_TRANSFORM", "connect", "function", "http_api_event", "schedule_event", "sqs_event", "table", "template"]
