"""An HTTP API in front of a Lambda, optionally behind a JWT authorizer. Sections feed docs/patterns/http-api.md."""

# --8<-- [start:http_api]
import re
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass

from cfn_typed_sumo.types import apigatewayv2 as apigw
from cfn_typed_sumo.types import lambda_

from cfn_typed import Expr, Resources, get_att, join, ref


@dataclass(frozen=True)
class Jwt:
    """Who may call: tokens from `issuer` whose audience is one of `audience`.

    `issuer` is the OIDC issuer URL, e.g. `https://cognito-idp.eu-west-1.amazonaws.com/eu-west-1_abc`.
    """

    issuer: Expr[str]
    audience: Sequence[Expr[str]]
    identity_source: str = "$request.header.Authorization"


@dataclass(frozen=True)
class HttpApi:
    """The handle `http_api` returns: the logical IDs, how to refer to them, and the resources."""

    api: str
    stage: str
    resources: Resources

    @property
    def api_id(self) -> Expr[str]:
        return ref(self.api)

    @property
    def endpoint(self) -> Expr[str]:
        """`https://{id}.execute-api.{region}.amazonaws.com`, without the stage."""
        return get_att(self.api, "ApiEndpoint")


def route_id(route_key: str) -> str:
    """A logical ID for a route key: `GET /orders/{id}` becomes `GetOrdersId`."""
    return "".join(word.capitalize() for word in re.findall(r"[A-Za-z0-9]+", route_key)) or "Default"


def http_api(
    name: str,
    *,
    function: str,
    routes: Sequence[str],
    jwt: Jwt | None = None,
    public: Collection[str] = (),
    scopes: Mapping[str, Sequence[str]] | None = None,
    cors_origins: Sequence[Expr[str]] | None = None,
    stage_name: str = "$default",
    tags: Mapping[str, Expr[str]] | None = None,
) -> HttpApi:
    """An HTTP API sending every route in `routes` (e.g. `"GET /orders"`) to the Lambda `function` (a logical ID).

    With `jwt`, every route requires a valid token except those in `public`; `scopes` maps a route to the
    scopes its token must carry. Logical IDs are `{name}Api`, `{name}Integration`, `{name}Authorizer`,
    `{name}Stage`, `{name}InvokePermission` and one `{name}Route...` per route.
    """
    unknown = (set(public) | set(scopes or {})) - set(routes)
    if unknown:
        raise ValueError(f"not routes of this API: {', '.join(sorted(unknown))}")
    if (public or scopes) and jwt is None:
        raise ValueError("`public` and `scopes` only mean something with `jwt`")
    api_id, integration_id, authorizer_id, stage_id = f"{name}Api", f"{name}Integration", f"{name}Authorizer", f"{name}Stage"

    api_props: apigw.ApiProps = {"Name": name, "ProtocolType": "HTTP"}
    if cors_origins:
        api_props["CorsConfiguration"] = {"AllowOrigins": list(cors_origins), "AllowMethods": ["*"], "AllowHeaders": ["*"]}
    if tags:
        api_props["Tags"] = tags
    resources: Resources = {
        api_id: apigw.api(**api_props),
        integration_id: apigw.integration(
            ApiId=ref(api_id),
            IntegrationType="AWS_PROXY",
            IntegrationUri=get_att(function, "Arn"),
            PayloadFormatVersion="2.0",
        ),
        stage_id: apigw.stage(ApiId=ref(api_id), StageName=stage_name, AutoDeploy=True),
        f"{name}InvokePermission": lambda_.permission(
            Action="lambda:InvokeFunction",
            FunctionName=get_att(function, "Arn"),
            Principal="apigateway.amazonaws.com",
            SourceArn=f"arn:${{AWS::Partition}}:execute-api:${{AWS::Region}}:${{AWS::AccountId}}:${{{api_id}}}/*",
        ),
    }
    if jwt:
        resources[authorizer_id] = apigw.authorizer(
            ApiId=ref(api_id),
            Name=f"{name}-jwt",
            AuthorizerType="JWT",
            IdentitySource=[jwt.identity_source],
            JwtConfiguration={"Issuer": jwt.issuer, "Audience": list(jwt.audience)},
        )
    for key in routes:
        route: apigw.RouteProps = {
            "ApiId": ref(api_id),
            "RouteKey": key,
            "Target": join("/", ["integrations", ref(integration_id)]),
        }
        if jwt and key not in public:
            route["AuthorizationType"] = "JWT"
            route["AuthorizerId"] = ref(authorizer_id)
            if scopes and key in scopes:
                route["AuthorizationScopes"] = list(scopes[key])
        resources[f"{name}Route{route_id(key)}"] = apigw.route(**route)
    return HttpApi(api_id, stage_id, resources)
# --8<-- [end:http_api]
