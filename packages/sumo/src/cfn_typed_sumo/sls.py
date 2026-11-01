"""The Serverless Framework's resources, with the framework's logical IDs (docs/patterns/eject-serverless.md).

Each function writes what `sls package` writes for the same `serverless.yml` entry, and under the same logical IDs, so
a service ejected with these renders to the template CloudFormation already has, and a deploy replaces nothing. The
other patterns pick their own IDs; use these for a service that is already deployed under the framework's.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from cfn_typed import (
    AnyStatement,
    Expr,
    Output,
    Resources,
    Tag,
    get_att,
    join,
    ref,
    sub,
)
from cfn_typed_sumo.types import (
    apigateway,
    apigatewayv2,
    events,
    iam,
    lambda_,
    logs,
    s3,
)

BUCKET = "ServerlessDeploymentBucket"
ROLE = "IamRoleLambdaExecution"


def logical(key: str) -> str:
    """The framework's logical name for a `functions:` key: `api_handler` is `ApiUnderscorehandler`, `my-fn` is `MyDashfn`."""
    return key[:1].upper() + key[1:].replace("-", "Dash").replace("_", "Underscore")


def deployment_bucket() -> Resources:
    """`ServerlessDeploymentBucket` and its policy, which denies requests that are not over TLS."""
    bucket = lambda s: join("", ["arn:", ref("AWS::Partition"), ":s3:::", ref(BUCKET), *s])
    return {
        BUCKET: s3.bucket(
            BucketEncryption={"ServerSideEncryptionConfiguration": [{"ServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]},
        ),
        f"{BUCKET}Policy": s3.bucket_policy(
            Bucket=ref(BUCKET),
            PolicyDocument={"Statement": [{
                "Action": "s3:*",
                "Effect": "Deny",
                "Principal": "*",
                "Resource": [bucket(["/*"]), bucket([])],
                "Condition": {"Bool": {"aws:SecureTransport": False}},
            }]},
        ),
    }


def iam_role(
    service: str,
    stage: str,
    statements: Sequence[AnyStatement] = (),
    *,
    managed_policies: Sequence[Expr[str]] = (),
) -> Resources:
    """`IamRoleLambdaExecution`, the one role every function in the service shares.

    The framework writes the log statements itself, scoped to `{service}-{stage}`, so they are not in `statements`.
    What an event needs, such as `sqs:ReceiveMessage` for an `sqs` event, is: pass it here.
    """
    logs_arn = f"arn:${{AWS::Partition}}:logs:${{AWS::Region}}:${{AWS::AccountId}}:log-group:/aws/lambda/{service}-{stage}*:*"
    props: iam.RoleProps = {
        "AssumeRolePolicyDocument": {
            "Version": "2012-10-17",
            "Statement": [{"Effect": "Allow", "Principal": {"Service": ["lambda.amazonaws.com"]}, "Action": ["sts:AssumeRole"]}],
        },
        "Policies": [{
            "PolicyName": join("-", [service, stage, "lambda"]),
            "PolicyDocument": {"Version": "2012-10-17", "Statement": [
                {"Effect": "Allow", "Action": ["logs:CreateLogStream", "logs:CreateLogGroup", "logs:TagResource"], "Resource": [sub(logs_arn)]},
                {"Effect": "Allow", "Action": ["logs:PutLogEvents"], "Resource": [sub(logs_arn + ":*")]},
                *statements,
            ]},
        }],
        "Path": "/",
        "RoleName": join("-", [service, stage, ref("AWS::Region"), "lambdaRole"]),
    }
    if managed_policies:
        props["ManagedPolicyArns"] = list(managed_policies)
    return {ROLE: iam.role(**props)}


@dataclass(frozen=True)
class Function:
    """What `function` returns: the logical IDs to refer to, and the three resources."""

    function: str
    log_group: str
    version: str
    resources: Resources

    @property
    def arn(self) -> Expr[str]:
        return get_att(self.function, "Arn")


def function(
    key: str,
    *,
    service: str,
    stage: str,
    s3_key: str,
    handler: str,
    runtime: str,
    code_sha256: str,
    version_id: str,
    memory: int = 1024,
    timeout: int = 6,
    environment: Mapping[str, Expr[str]] | None = None,
    tags: list[Expr[Tag]] | None = None,
    log_retention_days: int | None = None,
    log_destination: Expr[str] | None = None,
) -> Function:
    """A `functions:` entry: `{Key}LogGroup`, `{Key}LambdaFunction` and `{Key}LambdaVersion{version_id}`, and `{Key}LogSubscriptionFilter` with `log_destination`.

    `s3_key` is where the zip is in the deployment bucket, and `version_id` is the suffix the framework put on the
    version's logical ID (a hash it computes; it is in the template you are ejecting from). The function is named
    `{service}-{stage}-{key}`, as the framework names it.
    """
    name = logical(key)
    log_group, fn, version = f"{name}LogGroup", f"{name}LambdaFunction", f"{name}LambdaVersion{version_id}"
    name_in_aws = f"{service}-{stage}-{key}"
    logs_props: logs.LogGroupProps = {"LogGroupName": f"/aws/lambda/{name_in_aws}"}
    props: lambda_.FunctionProps = {
        "Code": {"S3Bucket": ref(BUCKET), "S3Key": s3_key},
        "Handler": handler,
        "Runtime": runtime,
        "FunctionName": name_in_aws,
        "MemorySize": memory,
        "Timeout": timeout,
        "Role": get_att(ROLE, "Arn"),
    }
    if log_retention_days is not None:
        logs_props["RetentionInDays"] = log_retention_days
    if environment:
        props["Environment"] = {"Variables": environment}
    if tags:
        logs_props["Tags"] = props["Tags"] = tags
    resources: Resources = {
        log_group: logs.log_group(**logs_props),
        fn: lambda_.function(depends_on=[log_group], **props),
        version: lambda_.version(deletion_policy="Retain", FunctionName=ref(fn), CodeSha256=code_sha256),
    }
    if log_destination is not None:
        resources[f"{name}LogSubscriptionFilter"] = logs.subscription_filter(
            depends_on=[log_group], LogGroupName=f"/aws/lambda/{name_in_aws}", FilterPattern="", DestinationArn=log_destination,
        )
    return Function(fn, log_group, version, resources)


def schedule_event(key: str, expression: str, *, number: int = 1, enabled: bool = True) -> Resources:
    """A `schedule` event: `{Key}EventsRuleSchedule{n}` and `{Key}LambdaPermissionEventsRuleSchedule{n}`."""
    name, rule = logical(key), f"{logical(key)}EventsRuleSchedule{number}"
    return {
        rule: events.rule(
            ScheduleExpression=expression,
            State="ENABLED" if enabled else "DISABLED",
            Targets=[{"Arn": get_att(f"{name}LambdaFunction", "Arn"), "Id": f"{key}Schedule{number if number > 1 else ''}"}],
        ),
        f"{name}LambdaPermissionEventsRuleSchedule{number}": lambda_.permission(
            FunctionName=get_att(f"{name}LambdaFunction", "Arn"),
            Action="lambda:InvokeFunction",
            Principal="events.amazonaws.com",
            SourceArn=get_att(rule, "Arn"),
        ),
    }


def sqs_event(key: str, queue: str, *, batch_size: int = 10) -> Resources:
    """An `sqs` event: `{Key}EventSourceMappingSQS{Queue}`, for a queue that is a resource in this template.

    The framework also adds the statements that let the role read the queue; see `sqs_statement`.
    """
    return {f"{logical(key)}EventSourceMappingSQS{queue}": lambda_.event_source_mapping(
        depends_on=ROLE,
        BatchSize=batch_size,
        EventSourceArn=get_att(queue, "Arn"),
        FunctionName=get_att(f"{logical(key)}LambdaFunction", "Arn"),
        Enabled=True,
    )}


def sqs_statement(*queues: str) -> AnyStatement:
    """What the framework adds to the shared role for `sqs` events. Pass it to `iam_role`."""
    return {
        "Effect": "Allow",
        "Action": ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"],
        "Resource": [get_att(queue, "Arn") for queue in queues],
    }


def path_id(path: str) -> str:
    """A route path as the framework writes it in logical IDs: `/todos/{id}` is `TodosIdVar`, `/` is empty."""
    parts = [part for part in path.split("/") if part]
    return "".join(logical(part.strip("{}+")) + "Var" if part.startswith("{") else logical(part) for part in parts)


@dataclass(frozen=True)
class Route:
    """One `http` event on a REST API: `Route("/todos/{id}", "GET", "todos")`. `function` is the `functions:` key."""

    path: str
    method: str
    function: str
    private: bool = False  # `private: true`, an API key is required


def _invocation(fn: str) -> Expr[str]:
    return join("", [
        "arn:", ref("AWS::Partition"), ":apigateway:", ref("AWS::Region"), ":lambda:path/2015-03-31/functions/",
        get_att(fn, "Arn"), "/invocations",
    ])


def _execute_api(api: str, tail: str) -> Expr[str]:
    return join("", [
        "arn:", ref("AWS::Partition"), ":execute-api:", ref("AWS::Region"), ":", ref("AWS::AccountId"), ":", ref(api), tail,
    ])


def rest_api(
    service: str,
    stage: str,
    routes: Sequence[Route],
    *,
    deployment_id: str = "",
    endpoint_type: str = "EDGE",
    api_key: bool | None = None,
) -> Resources:
    """`http` events on a REST API: the API, one `ApiGatewayResource…` per path segment, a method for each route and a
    mock `OPTIONS` method per path for CORS, the deployment, and a permission per function.

    `deployment_id` is the suffix on `ApiGatewayDeployment` (the framework puts a timestamp there). Routes with
    `private=True` bring the API key, usage plan and usage plan key, unless `api_key=False`.
    """
    api = "ApiGatewayRestApi"
    out: Resources = {api: apigateway.rest_api(Name=f"{stage}-{service}", EndpointConfiguration={"Types": [endpoint_type]})}
    paths = list(dict.fromkeys(route.path for route in routes))
    segments = list(dict.fromkeys(
        "/" + "/".join(parts[: i + 1]) for path in paths for parts in [[p for p in path.split("/") if p]] for i in range(len(parts))
    ))
    for segment in segments:
        parts = segment.strip("/").split("/")
        parent = "/" + "/".join(parts[:-1]) if len(parts) > 1 else None
        out[f"ApiGatewayResource{path_id(segment)}"] = apigateway.resource(
            ParentId=ref(f"ApiGatewayResource{path_id(parent)}") if parent else get_att(api, "RootResourceId"),
            PathPart=parts[-1],
            RestApiId=ref(api),
        )

    def resource_of(path: str) -> Expr[str]:
        return ref(f"ApiGatewayResource{path_id(path)}") if path_id(path) else get_att(api, "RootResourceId")

    methods: list[str] = []
    for route in routes:
        fn = f"{logical(route.function)}LambdaFunction"
        method_id = f"ApiGatewayMethod{path_id(route.path)}{route.method.capitalize()}"
        methods.append(method_id)
        out[method_id] = apigateway.method(
            HttpMethod=route.method.upper(),
            ResourceId=resource_of(route.path),
            RestApiId=ref(api),
            ApiKeyRequired=route.private,
            AuthorizationType="NONE",
            RequestParameters={},
            MethodResponses=[],
            Integration={"IntegrationHttpMethod": "POST", "Type": "AWS_PROXY", "Uri": _invocation(fn)},
        )
    for path in paths:
        verbs = ",".join(["OPTIONS", *(r.method.upper() for r in routes if r.path == path)])
        options_id = f"ApiGatewayMethod{path_id(path)}Options"
        methods.append(options_id)
        out[options_id] = _cors_options(resource_of(path), verbs)
    deployment = f"ApiGatewayDeployment{deployment_id}"
    out[deployment] = apigateway.deployment(depends_on=methods, RestApiId=ref(api), StageName=stage)
    for fn in dict.fromkeys(f"{logical(route.function)}LambdaFunction" for route in routes):
        out[f"{fn.removesuffix('LambdaFunction')}LambdaPermissionApiGateway"] = lambda_.permission(
            FunctionName=get_att(fn, "Arn"),
            Action="lambda:InvokeFunction",
            Principal="apigateway.amazonaws.com",
            SourceArn=_execute_api(api, "/*/*"),
        )
    if api_key if api_key is not None else any(route.private for route in routes):
        out["ApiGatewayApiKey1"] = apigateway.api_key(
            depends_on=deployment, Enabled=True, Name=f"{service}-{stage}-apikey",
            StageKeys=[{"RestApiId": ref(api), "StageName": stage}],
        )
        out["ApiGatewayUsagePlan"] = apigateway.usage_plan(
            depends_on=deployment,
            ApiStages=[{"ApiId": ref(api), "Stage": stage}],
            Description=f"Usage plan for {service} {stage} stage",
            UsagePlanName=f"{service}-{stage}",
        )
        out["ApiGatewayUsagePlanKey1"] = apigateway.usage_plan_key(
            KeyId=ref("ApiGatewayApiKey1"), KeyType="API_KEY", UsagePlanId=ref("ApiGatewayUsagePlan"),
        )
    return out


def _cors_options(resource: Expr[str], verbs: str) -> apigateway.Method:
    header = "method.response.header.Access-Control-Allow-"
    return apigateway.method(
        AuthorizationType="NONE",
        HttpMethod="OPTIONS",
        RequestParameters={},
        ResourceId=resource,
        RestApiId=ref("ApiGatewayRestApi"),
        Integration={
            "Type": "MOCK",
            "RequestTemplates": {"application/json": "{statusCode:200}"},
            "ContentHandling": "CONVERT_TO_TEXT",
            "IntegrationResponses": [{
                "StatusCode": "200",
                "ResponseParameters": {
                    f"{header}Origin": "'*'",
                    f"{header}Headers": "'Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token,X-Amz-User-Agent'",
                    f"{header}Methods": f"'{verbs}'",
                },
                "ResponseTemplates": {"application/json": ""},
            }],
        },
        MethodResponses=[{
            "StatusCode": "200",
            "ResponseParameters": {f"{header}Origin": True, f"{header}Headers": True, f"{header}Methods": True},
            "ResponseModels": {},
        }],
    )


@dataclass(frozen=True)
class HttpRoute:
    """One `httpApi` event: `HttpRoute("GET", "/users/{id}", "users", authorizer="auth0")`."""

    method: str
    path: str
    function: str
    authorizer: str | None = None


@dataclass(frozen=True)
class JwtAuthorizer:
    issuer: str
    audience: Sequence[str]


def http_api(name: str, routes: Sequence[HttpRoute], *, authorizers: Mapping[str, JwtAuthorizer] | None = None) -> Resources:
    """`httpApi` events: `HttpApi` and `HttpApiStage`, a `HttpApiAuthorizer{Name}` for each JWT authorizer, a
    `HttpApiIntegration{Key}` and a `HttpApiRoute{Method}{Path}` per route, and `{Key}LambdaPermissionHttpApi`."""
    api = "HttpApi"
    out: Resources = {
        api: apigatewayv2.api(Name=name, ProtocolType="HTTP"),
        f"{api}Stage": apigatewayv2.stage(
            ApiId=ref(api), StageName="$default", AutoDeploy=True, DefaultRouteSettings={"DetailedMetricsEnabled": False},
        ),
    }
    for auth_name, auth in (authorizers or {}).items():
        out[f"{api}Authorizer{logical(auth_name)}"] = apigatewayv2.authorizer(
            ApiId=ref(api),
            Name=auth_name,
            IdentitySource=["$request.header.Authorization"],
            AuthorizerType="JWT",
            JwtConfiguration={"Audience": list(auth.audience), "Issuer": auth.issuer},
        )
    for key in dict.fromkeys(route.function for route in routes):
        integration = f"{api}Integration{logical(key)}"
        out[integration] = apigatewayv2.integration(
            ApiId=ref(api),
            IntegrationType="AWS_PROXY",
            IntegrationUri=get_att(f"{logical(key)}LambdaFunction", "Arn"),
            PayloadFormatVersion="2.0",
            TimeoutInMillis=30000,
        )
        for route in (r for r in routes if r.function == key):
            props: apigatewayv2.RouteProps = {
                "ApiId": ref(api),
                "RouteKey": f"{route.method.upper()} {route.path}",
                "Target": join("/", ["integrations", ref(integration)]),
            }
            if route.authorizer:
                props["AuthorizationType"] = "JWT"
                props["AuthorizerId"] = ref(f"{api}Authorizer{logical(route.authorizer)}")
            out[f"{api}Route{route.method.capitalize()}{path_id(route.path)}"] = apigatewayv2.route(**props)
        out[f"{logical(key)}LambdaPermissionHttpApi"] = lambda_.permission(
            FunctionName=get_att(f"{logical(key)}LambdaFunction", "Arn"),
            Action="lambda:InvokeFunction",
            Principal="apigateway.amazonaws.com",
            SourceArn=_execute_api(api, "/*"),
        )
    return out


def outputs(service: str, stage: str, *functions: Function) -> dict[str, Output]:
    """The outputs the framework adds: the bucket name, and each function's current version."""
    prefix = f"sls-{service}-{stage}"
    out: dict[str, Output] = {
        f"{BUCKET}Name": {"Value": ref(BUCKET), "Export": {"Name": f"{prefix}-{BUCKET}Name"}},
    }
    for fn in functions:
        name = fn.function.removesuffix("LambdaFunction")
        out[f"{name}LambdaFunctionQualifiedArn"] = {
            "Description": "Current Lambda function version",
            "Value": ref(fn.version),
            "Export": {"Name": f"{prefix}-{name}LambdaFunctionQualifiedArn"},
        }
    return out


def endpoint_outputs(service: str, stage: str, *, rest: bool = False, http: bool = False) -> dict[str, Output]:
    """The outputs for the API URLs: `ServiceEndpoint` for a REST API, `HttpApiUrl` for an HTTP API."""
    prefix = f"sls-{service}-{stage}"
    out: dict[str, Output] = {}
    if rest:
        out["ServiceEndpoint"] = {
            "Description": "URL of the service endpoint",
            "Value": sub(f"https://${{ApiGatewayRestApi}}.execute-api.${{AWS::Region}}.${{AWS::URLSuffix}}/{stage}"),
            "Export": {"Name": f"{prefix}-ServiceEndpoint"},
        }
    if http:
        out["HttpApiUrl"] = {
            "Description": "URL of the HTTP API",
            "Value": sub("https://${HttpApi}.execute-api.${AWS::Region}.${AWS::URLSuffix}"),
            "Export": {"Name": f"{prefix}-HttpApiUrl"},
        }
    return out
