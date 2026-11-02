"""`cfn-typed import --sls`: a template that `sls package` wrote, as Python that calls `cfn_typed_sumo.sls`.

    sls package
    cfn-typegen --out cfn_types --template .serverless/cloudformation-template-update-stack.json
    cfn-typed import --sls .serverless/cloudformation-template-update-stack.json -o stack.py

The plain `import` keeps every resource as a call to its factory. This one also looks for what the framework wrote for a
`functions:` entry, an event, an API or a role, and writes the `sls.function(...)` or `sls.rest_api(...)` call for it.

Nothing is guessed. Each call is made while importing, and its resources are compared with the ones in the template: only
when they are equal is the group written as a call. A group that differs by one property (a framework version that wrote it
another way) stays as the plain resources, which is the same template, so the result always renders to the original. The
header of the module lists what was kept plain.
"""

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from cfn_typed.importer import _SECTIONS, _Writer, _q
from cfn_typed_sumo import sls

_SQS = re.compile(r"(?P<fn>.+)EventSourceMappingSQS(?P<queue>.+)")
_STREAM = re.compile(r"(?P<fn>.+)EventSourceMapping(?P<kind>Dynamodb|Kinesis)(?P<name>.+)")
_SCHEDULE = re.compile(r"(?P<fn>.+)EventsRuleSchedule(?P<n>\d+)")
_SNS = re.compile(r"(?P<fn>.+)SnsSubscription(?P<name>.+)")
_DEFAULT_LOG_ACTIONS = ["logs:CreateLogStream", "logs:CreateLogGroup", "logs:TagResource"]


def _same(a: Any, b: Any) -> bool:
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def _is_ref(value: Any) -> str | None:
    return value["Ref"] if isinstance(value, Mapping) and set(value) == {"Ref"} and isinstance(value["Ref"], str) else None


def _get_att(value: Any) -> tuple[str, str] | None:
    if isinstance(value, Mapping) and set(value) == {"Fn::GetAtt"}:
        match value["Fn::GetAtt"]:
            case [str() as logical, str() as attr]:
                return logical, attr
    return None


def _snake(key: str) -> str:
    return re.sub(r"\W", "_", key)


@dataclass
class _Import:
    template: Mapping[str, Any]
    writer: _Writer = field(default_factory=_Writer)
    claimed: set[str] = field(default_factory=set)
    outputs_claimed: set[str] = field(default_factory=set)
    lines: list[str] = field(default_factory=list)  # statements in build()
    parts: list[str] = field(default_factory=list)  # arguments of combine()
    service: str = ""
    stage: str = ""
    keys: dict[str, str] = field(default_factory=dict)  # `{Name}LambdaFunction` -> the `functions:` key
    functions: dict[str, sls.Function] = field(default_factory=dict)
    kept: list[str] = field(default_factory=list)

    @property
    def resources(self) -> Mapping[str, Any]:
        return self.template.get("Resources") or {}

    def lit(self, value: Any, level: int = 2) -> str:
        return self.writer.lit(value, level)

    def claim(self, produced: Mapping[str, Any]) -> bool:
        """True, and the ids are the call's from now on, when every resource the call writes is in the template, equal and not claimed."""
        ok = all(k in self.resources and k not in self.claimed and _same(v, self.resources[k]) for k, v in produced.items())
        if ok:
            self.claimed |= set(produced)
        return ok

    def add(self, call: str, produced: Mapping[str, Any], what: str) -> bool:
        """Write `call` as part of the module if it renders `produced` exactly."""
        if self.claim(produced):
            self.parts.append(call)
            return True
        self.kept.append(what)
        return False

    # -- the role and the bucket --------------------------------------------------------------------------------

    def find_service(self) -> bool:
        role = self.resources.get(sls.ROLE) or {}
        try:
            name = role["Properties"]["Policies"][0]["PolicyName"]["Fn::Join"]
            sep, (service, stage, tail) = name
        except (KeyError, TypeError, ValueError, IndexError):
            return False
        if sep != "-" or tail != "lambda" or not isinstance(service, str) or not isinstance(stage, str):
            return False
        self.service, self.stage = service, stage
        return True

    def bucket(self) -> None:
        if sls.BUCKET in self.resources:
            self.add("sls.deployment_bucket()", sls.deployment_bucket(), "the deployment bucket")

    def statement_source(self, statement: Mapping[str, Any]) -> str:
        actions, resource = statement.get("Action"), statement.get("Resource")
        if isinstance(resource, list) and resource:
            queues = [att[0] for r in resource if (att := _get_att(r)) and att[1] == "Arn"]
            if len(queues) == len(resource) and _same(statement, sls.sqs_statement(*queues)):
                return "sls.sqs_statement(" + ", ".join(_q(queue) for queue in queues) + ")"
        if _same(statement, sls.vpc_statement()):
            return "sls.vpc_statement()"
        for kind in ("dynamodb", "kinesis"):
            if isinstance(resource, list) and isinstance(actions, list) and actions[:1] == [f"{kind}:GetRecords"]:
                if _same(statement, sls.stream_statement(kind, *resource)):
                    return f"sls.stream_statement({_q(kind)}, " + ", ".join(self.lit(r, 4) for r in resource) + ")"
        return self.lit(statement, 4)

    def role(self) -> None:
        if sls.ROLE not in self.resources:
            return
        props = self.resources[sls.ROLE].get("Properties", {})
        try:
            statements = props["Policies"][0]["PolicyDocument"]["Statement"]
        except (KeyError, IndexError, TypeError):
            statements = []
        if len(statements) < 2:
            self.kept.append("the role")
            return
        log_actions = statements[0].get("Action", [])
        extra = statements[2:]
        managed = props.get("ManagedPolicyArns") or ()
        kwargs = {"managed_policies": managed} if managed else {}
        if log_actions != _DEFAULT_LOG_ACTIONS:
            kwargs["log_actions"] = log_actions
        produced = sls.iam_role(self.service, self.stage, extra, **kwargs)
        if not self.claim(produced):
            self.kept.append("the role")
            return
        args = ["SERVICE", "STAGE"]
        if extra:
            args.append("[\n" + "".join(f"                {self.statement_source(st)},\n" for st in extra) + "            ]")
        if managed:
            args.append(f"managed_policies={self.lit(list(managed))}")
        if "log_actions" in kwargs:
            args.append(f"log_actions={self.lit(log_actions)}")
        self.parts.append("sls.iam_role(" + ", ".join(args) + ")")

    # -- functions and what triggers them -------------------------------------------------------------------------

    def function(self, name: str) -> None:
        res = self.resources
        fn, group = res[f"{name}LambdaFunction"], res.get(f"{name}LogGroup")
        versions = [k for k, v in res.items() if k.startswith(f"{name}LambdaVersion") and v.get("Type") == "AWS::Lambda::Version"]
        props = fn.get("Properties", {})
        fn_name = props.get("FunctionName")
        prefix = f"{self.service}-{self.stage}-" if self.service else None
        default_name = prefix is not None and isinstance(fn_name, str) and fn_name.startswith(prefix) and sls.logical(fn_name[len(prefix):]) == name
        if group is None or len(versions) > 1 or not isinstance(fn_name, str) or not (default_name or props.get("FunctionName")):
            self.kept.append(f"{name}LambdaFunction")
            return
        key = fn_name[len(prefix):] if default_name and prefix else name[:1].lower() + name[1:]
        gprops = group.get("Properties", {})
        version = res[versions[0]] if versions else None
        sub = res.get(f"{name}LogSubscriptionFilter")
        code, vpc = props.get("Code", {}), props.get("VpcConfig")
        kwargs: dict[str, Any] = {"s3_key": code.get("S3Key"), "handler": props.get("Handler"), "runtime": props.get("Runtime")}
        if not default_name:
            kwargs["name"] = fn_name
        if version is not None:
            kwargs["code_sha256"] = version.get("Properties", {}).get("CodeSha256")
            kwargs["version_id"] = versions[0][len(f"{name}LambdaVersion"):]
        else:
            kwargs["versioned"] = False
        if _is_ref(code.get("S3Bucket")) != sls.BUCKET and isinstance(code.get("S3Bucket"), (str, Mapping)):
            kwargs["bucket"] = code["S3Bucket"]
        if _get_att(props.get("Role")) != (sls.ROLE, "Arn") and props.get("Role") is not None:
            kwargs["role"] = props["Role"]
        optional: dict[str, Any] = {
            "memory": props.get("MemorySize"), "timeout": props.get("Timeout"),
            "environment": (props.get("Environment") or {}).get("Variables"), "tags": props.get("Tags"),
            "log_retention_days": gprops.get("RetentionInDays"),
            "log_destination": sub.get("Properties", {}).get("DestinationArn") if sub else None,
            "layers": props.get("Layers"), "description": props.get("Description"), "reserved_concurrency": props.get("ReservedConcurrentExecutions"),
        }
        kwargs |= {k: v for k, v in optional.items() if v is not None}
        if vpc is not None:
            kwargs["vpc"] = sls.Vpc(vpc.get("SecurityGroupIds", []), vpc.get("SubnetIds", []))
        if any(not isinstance(kwargs[k], str) for k in ("s3_key", "handler", "runtime")) or ("code_sha256" in kwargs and not isinstance(kwargs["code_sha256"], str)):
            self.kept.append(f"{name}LambdaFunction")
            return
        for number in ("memory", "timeout", "log_retention_days", "reserved_concurrency"):
            if number in kwargs and not isinstance(kwargs[number], int):
                self.kept.append(f"{name}LambdaFunction")
                return
        try:
            built = sls.function(key, service=self.service if default_name else "", stage=self.stage if default_name else "", **kwargs)
        except (TypeError, ValueError):
            self.kept.append(f"{name}LambdaFunction")
            return
        if not self.claim(built.resources):
            self.kept.append(f"{name}LambdaFunction")
            return
        var = f"fn_{_snake(key)}"
        order = ["s3_key", "handler", "runtime", "name", "bucket", "versioned", "role", "memory", "timeout", "environment", "tags", "log_retention_days",
                 "log_destination", "vpc", "layers", "description", "reserved_concurrency", "code_sha256", "version_id"]
        args = [f"        {_q(key)},"] + (["        service=SERVICE,", "        stage=STAGE,"] if default_name else [])
        for k in order:
            if k not in kwargs:
                continue
            v = kwargs[k]
            text = f"sls.Vpc({self.lit(list(v.security_group_ids), 2)}, {self.lit(list(v.subnet_ids), 2)})" if k == "vpc" else self.lit(v, 2)
            args.append(f"        {k}={text},")
        self.lines.append(f"    {var} = sls.function(\n" + "\n".join(args) + "\n    )")
        self.parts.append(var)
        self.keys[f"{name}LambdaFunction"] = key
        self.functions[key] = built

    def events(self) -> None:
        for logical, res in list(self.resources.items()):
            if logical in self.claimed:
                continue
            props = res.get("Properties", {})
            if res.get("Type") == "AWS::Events::Rule" and (m := _SCHEDULE.fullmatch(logical)):
                key = self.keys.get(f"{m['fn']}LambdaFunction")
                expression, state = props.get("ScheduleExpression"), props.get("State")
                if key and isinstance(expression, str) and state in ("ENABLED", "DISABLED"):
                    number, enabled = int(m["n"]), state == "ENABLED"
                    extra = ("" if number == 1 else f", number={number}") + ("" if enabled else ", enabled=False")
                    self.add(f"sls.schedule_event({_q(key)}, {_q(expression)}{extra})",
                             sls.schedule_event(key, expression, number=number, enabled=enabled), logical)
                    continue
            if res.get("Type") == "AWS::Lambda::EventSourceMapping" and (m := _SQS.fullmatch(logical)):
                key = self.keys.get(f"{m['fn']}LambdaFunction")
                batch = props.get("BatchSize")
                if key and isinstance(batch, int):
                    extra = "" if batch == 10 else f", batch_size={batch}"
                    self.add(f"sls.sqs_event({_q(key)}, {_q(m['queue'])}{extra})", sls.sqs_event(key, m["queue"], batch_size=batch), logical)
                    continue
            if res.get("Type") == "AWS::Lambda::EventSourceMapping" and (m := _STREAM.fullmatch(logical)):
                key, att = self.keys.get(f"{m['fn']}LambdaFunction"), _get_att(props.get("EventSourceArn"))
                kind = m["kind"].lower()
                if key and att and isinstance(props.get("BatchSize"), int):
                    stream = att[0]
                    kwargs = {"kind": kind, "batch_size": props["BatchSize"], "starting_position": props.get("StartingPosition", "TRIM_HORIZON"),
                              "enabled": props.get("Enabled", True), "name": m["name"]}
                    if (m["name"] == stream):
                        kwargs.pop("name")
                    text = f"sls.stream_event({_q(key)}, {_q(stream)}, kind={_q(kind)}, batch_size={props['BatchSize']}"
                    if kwargs.get("starting_position") != "TRIM_HORIZON":
                        text += f", starting_position={_q(kwargs['starting_position'])}"
                    if kwargs["enabled"] is not True:
                        text += ", enabled=False"
                    if "name" in kwargs:
                        text += f", name={_q(m['name'])}"
                    self.add(text + ")", sls.stream_event(key, stream, **kwargs), logical)
                    continue
            if res.get("Type") == "AWS::SNS::Subscription" and (m := _SNS.fullmatch(logical)):
                key, topic = self.keys.get(f"{m['fn']}LambdaFunction"), _is_ref(props.get("TopicArn"))
                if key and topic:
                    default = topic.removeprefix("SNSTopic")
                    extra = "" if default == m["name"] else f", name={_q(m['name'])}"
                    self.add(f"sls.sns_event({_q(key)}, {_q(topic)}{extra})", sls.sns_event(key, topic, name=m["name"]), logical)

    # -- the APIs -------------------------------------------------------------------------------------------------

    def _key_of(self, uri: Any) -> str | None:
        found: list[str] = []

        def walk(value: Any) -> None:
            if (att := _get_att(value)) and att[1] == "Arn":
                found.append(att[0])
            elif isinstance(value, Mapping):
                for v in value.values():
                    walk(v)
            elif isinstance(value, list):
                for v in value:
                    walk(v)

        walk(uri)
        return self.keys.get(found[0]) if len(found) == 1 else None

    def _path_of(self, resource_id: Any, api: str) -> str | None:
        if (att := _get_att(resource_id)) and att == (api, "RootResourceId"):
            return "/"
        rid = _is_ref(resource_id)
        res = self.resources.get(rid) if rid else None
        if not res or res.get("Type") != "AWS::ApiGateway::Resource":
            return None
        props = res["Properties"]
        parent = self._path_of(props.get("ParentId"), api)
        if parent is None or not isinstance(props.get("PathPart"), str):
            return None
        return ("" if parent == "/" else parent) + "/" + props["PathPart"]

    def rest_api(self) -> None:
        api = "ApiGatewayRestApi"
        if api not in self.resources:
            return
        res = self.resources
        routes: list[str] = []
        route_objects: list[sls.Route] = []
        authorizers: dict[str, sls.Authorizer] = {}
        auth_names: dict[str, str] = {}
        for logical, r in res.items():
            if r.get("Type") == "AWS::ApiGateway::Authorizer":
                p = r.get("Properties", {})
                key = self._key_of(p.get("AuthorizerUri"))
                if key and isinstance(p.get("Name"), str) and logical == f"{sls.logical(p['Name'])}ApiGatewayAuthorizer":
                    authorizers[p["Name"]] = sls.Authorizer(
                        key, p.get("Type", "TOKEN"), p.get("IdentitySource", ""), p.get("AuthorizerResultTtlInSeconds"), p.get("IdentityValidationExpression"),
                    )
                    auth_names[logical] = p["Name"]
        for logical, r in res.items():
            p = r.get("Properties", {})
            if r.get("Type") != "AWS::ApiGateway::Method" or (p.get("Integration") or {}).get("Type") != "AWS_PROXY":
                continue
            path, key = self._path_of(p.get("ResourceId"), api), self._key_of(p["Integration"].get("Uri"))
            auth = auth_names.get(_is_ref(p.get("AuthorizerId")) or "")
            if path is None or key is None or not isinstance(p.get("HttpMethod"), str):
                self.kept.append("the REST API")
                return
            route_objects.append(sls.Route(path, p["HttpMethod"], key, p.get("ApiKeyRequired") is True, auth))
            routes.append(f"sls.Route({_q(path)}, {_q(p['HttpMethod'])}, {_q(key)}"
                          + (", private=True" if p.get("ApiKeyRequired") is True else "") + (f", authorizer={_q(auth)}" if auth else "") + ")")
        deployments = [k for k in res if k.startswith("ApiGatewayDeployment")]
        api_props = res[api].get("Properties", {})
        types = (api_props.get("EndpointConfiguration") or {}).get("Types") or ["EDGE"]
        binary = api_props.get("BinaryMediaTypes") or []
        if len(deployments) != 1 or not routes:
            self.kept.append("the REST API")
            return
        deployment_id = deployments[0][len("ApiGatewayDeployment"):]
        for api_key in (None, True, False):
            built = sls.rest_api(
                self.service, self.stage, route_objects, deployment_id=deployment_id, endpoint_type=types[0], api_key=api_key,
                binary_media_types=binary, authorizers=authorizers or None,
            )
            if all(k in res and _same(v, res[k]) and k not in self.claimed for k, v in built.items()):
                break
        else:
            self.kept.append("the REST API")
            return
        self.claim(built)
        args = ["SERVICE", "STAGE", "[\n" + "".join(f"                {route},\n" for route in routes) + "            ]"]
        if deployment_id:
            args.append(f"deployment_id={_q(deployment_id)}")
        if types[0] != "EDGE":
            args.append(f"endpoint_type={_q(types[0])}")
        if api_key is not None:
            args.append(f"api_key={api_key}")
        if binary:
            args.append(f"binary_media_types={self.lit(list(binary))}")
        if authorizers:
            items = "".join(
                f"                {_q(n)}: sls.Authorizer({_q(a.function)}, {_q(a.type)}, {_q(a.identity_source)}, {a.result_ttl!r}, {a.validation!r}),\n"
                for n, a in authorizers.items()
            )
            args.append("authorizers={\n" + items + "            }")
        self.parts.append("sls.rest_api(" + ", ".join(args) + ")")
        self.rest = True

    rest = False
    http = False

    def http_api(self) -> None:
        api = "HttpApi"
        if api not in self.resources:
            return
        res = self.resources
        routes: list[sls.HttpRoute] = []
        authorizers: dict[str, sls.JwtAuthorizer] = {}
        auth_names: dict[str, str] = {}
        for logical, r in res.items():
            p = r.get("Properties", {})
            if r.get("Type") == "AWS::ApiGatewayV2::Authorizer":
                jwt = p.get("JwtConfiguration") or {}
                if isinstance(p.get("Name"), str) and isinstance(jwt.get("Issuer"), str) and isinstance(jwt.get("Audience"), list):
                    authorizers[p["Name"]] = sls.JwtAuthorizer(jwt["Issuer"], jwt["Audience"])
                    auth_names[logical] = p["Name"]
        for logical, r in res.items():
            p = r.get("Properties", {})
            if r.get("Type") != "AWS::ApiGatewayV2::Route":
                continue
            try:
                method, path = p["RouteKey"].split(" ", 1)
                integration = _is_ref(p["Target"]["Fn::Join"][1][1])
                key = self._key_of(res[integration or ""]["Properties"]["IntegrationUri"])
            except (KeyError, TypeError, ValueError, IndexError):
                key = None
            if key is None:
                self.kept.append("the HTTP API")
                return
            routes.append(sls.HttpRoute(method, path, key, auth_names.get(_is_ref(p.get("AuthorizerId")) or "")))
        name = res[api].get("Properties", {}).get("Name")
        if not routes or not isinstance(name, str):
            self.kept.append("the HTTP API")
            return
        built = sls.http_api(name, routes, authorizers=authorizers or None)
        if not self.claim(built):
            self.kept.append("the HTTP API")
            return
        rows = "".join(
            f"                sls.HttpRoute({_q(r.method)}, {_q(r.path)}, {_q(r.function)}" + (f", authorizer={_q(r.authorizer)}" if r.authorizer else "") + "),\n"
            for r in routes
        )
        args = [_q(name), "[\n" + rows + "            ]"]
        if authorizers:
            items = "".join(f"                {_q(n)}: sls.JwtAuthorizer({_q(a.issuer)}, {self.lit(list(a.audience), 4)}),\n" for n, a in authorizers.items())
            args.append("authorizers={\n" + items + "            }")
        self.parts.append("sls.http_api(" + ", ".join(args) + ")")
        self.http = True

    # -- outputs and the module -----------------------------------------------------------------------------------

    def outputs(self) -> list[str]:
        """The `Outputs` calls that render some of the template's outputs exactly."""
        have = self.template.get("Outputs") or {}
        calls: list[str] = []
        if not self.service:
            return calls
        names = list(self.functions)
        produced = sls.outputs(self.service, self.stage, *self.functions.values())
        if produced and all(k in have and _same(v, have[k]) for k, v in produced.items()):
            calls.append("sls.outputs(SERVICE, STAGE" + "".join(f", fn_{_snake(k)}" for k in names) + ")")
            self.outputs_claimed |= set(produced)
        else:  # the bucket output alone, or the ones that match
            for k, v in produced.items():
                if k in have and _same(v, have[k]):
                    self.outputs_claimed.add(k)
            if self.outputs_claimed:
                kept = [fn for fn in self.functions.values() if f"{fn.function.removesuffix('LambdaFunction')}LambdaFunctionQualifiedArn" in self.outputs_claimed]
                calls.append("sls.outputs(SERVICE, STAGE" + "".join(f", fn_{_snake(k)}" for k, f in self.functions.items() if f in kept) + ")")
        endpoint = sls.endpoint_outputs(self.service, self.stage, rest=self.rest, http=self.http)
        if endpoint and all(k in have and _same(v, have[k]) for k, v in endpoint.items()):
            calls.append(f"sls.endpoint_outputs(SERVICE, STAGE, rest={self.rest}, http={self.http})")
            self.outputs_claimed |= set(endpoint)
        return calls


def import_sls(template: Mapping[str, Any], types: str = "cfn_types") -> tuple[str, int]:
    """Python source of a module with `build() -> cfn.Template` for `template`, calling `cfn_typed_sumo.sls` wherever the call renders the same resources, and the number of resources those calls replaced. When that is 0 (a service with no functions, which is bucket and policy only; a template the framework did not write) the module is the plain import."""
    job = _Import(template)
    job.find_service()
    job.bucket()
    job.role()
    for logical in [k for k, v in job.resources.items() if k.endswith("LambdaFunction") and v.get("Type") == "AWS::Lambda::Function"]:
        job.function(logical.removesuffix("LambdaFunction"))
    job.events()
    job.rest_api()
    job.http_api()
    if not job.claimed:
        from cfn_typed.importer import to_python as plain

        return plain(template, types), 0
    output_calls = job.outputs()

    w = job.writer
    leftovers = [w.resource(logical, res, 4) for logical, res in job.resources.items() if logical not in job.claimed]
    if leftovers:
        job.parts.append("{\n" + "\n".join(leftovers) + "\n            }")
    body: list[str] = []
    for section in (*_SECTIONS, *sorted(set(template) - set(_SECTIONS))):
        if section not in template:
            continue
        if section == "Resources":
            body.append('        "Resources": cfn.combine(\n' + "".join(f"            {part},\n" for part in job.parts) + "        ),")
        elif section == "Outputs":
            rest = {k: v for k, v in template[section].items() if k not in job.outputs_claimed}
            pieces = [f"**{call}" for call in output_calls] + [f"{_q(k)}: {w.lit(v, 3)}" for k, v in rest.items()]
            body.append('        "Outputs": {' + ("\n" + "".join(f"            {p},\n" for p in pieces) + "        " if pieces else "") + "},")
        else:
            body.append(f"        {_q(section)}: {w.lit(template[section], 2)},")
    head = ["from cfn_typed_sumo import sls", "", "import cfn_typed as cfn"]
    known = [f"SERVICE, STAGE = {_q(job.service)}, {_q(job.stage)}", "", ""] if job.service else ["", ""]
    if w.modules:
        head.append(f"from {types} import {', '.join(sorted(w.modules))}")
    notes = [*(f"#   {n}" for n in w.notes), *(f"#   {k}" for k in job.kept)]
    return "\n".join([
        "# Imported by `cfn-typed import --sls`. Each sls.* call renders the resources it replaces, exactly; check the whole with `cfn-typed emit`.",
        *(["# Left as plain resources:", *dict.fromkeys(notes)] if notes else []),
        "",
        *head,
        "",
        *known,
        "def build() -> cfn.Template:",
        *job.lines,
        "    return {",
        *body,
        "    }",
        "",
    ]), len(job.claimed)


def to_python(template: Mapping[str, Any], types: str = "cfn_types") -> str:
    """`import_sls` without the count."""
    return import_sls(template, types)[0]


def main(path: str, out: str | None, types: str) -> int:
    """The `import --sls` subcommand."""
    import sys
    from pathlib import Path

    from cfn_typed.cli import load_template

    source, claimed = import_sls(load_template(Path(path)), types)
    if not claimed:
        print("--sls found nothing to write as a call (no function, event, API or role of the framework's): this is the plain import", file=sys.stderr)
    if out:
        Path(out).write_text(source)
        print(f"wrote {out}", file=sys.stderr)
    else:
        print(source, end="")
    return 0


__all__: Sequence[str] = ["import_sls", "main", "to_python"]
