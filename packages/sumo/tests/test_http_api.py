import pytest

from cfn_typed_sumo import Jwt, http_api, lambda_role
from cfn_typed_sumo.http_api import route_id
from cfn_typed_sumo.types import lambda_

from cfn_typed import combine, get_att, ref
from cfn_typed.query import prop
from cfn_typed.testing import assert_template_ok

ISSUER = "https://cognito-idp.eu-west-1.amazonaws.com/eu-west-1_abc"
JWT = Jwt(ISSUER, ["client-1"])


def stack(**kw):  # a Lambda to point at, so the references resolve
    api = http_api("Orders", function="Handler", routes=["GET /orders", "POST /orders", "GET /health"], **kw)
    handler = lambda_.function(
        Handler="index.handler", Runtime="python3.13", Role=get_att("Role", "Arn"), Code=lambda_.FunctionCode(ZipFile="x"),
    )
    return api, {"Resources": combine({"Role": lambda_role("orders", []), "Handler": handler}, api)}


def test_route_ids_are_valid_logical_ids() -> None:
    assert route_id("GET /orders/{id}") == "GetOrdersId"
    assert route_id("$default") == "Default"


def test_without_jwt_nothing_is_authorized_and_there_is_no_authorizer() -> None:
    api, template = stack()
    assert "OrdersAuthorizer" not in api.resources
    for logical_id, r in api.resources.items():
        if r["Type"] == "AWS::ApiGatewayV2::Route":
            assert "AuthorizationType" not in r["Properties"], logical_id
    assert_template_ok(template)


def test_jwt_protects_every_route_but_the_public_ones() -> None:
    api, template = stack(jwt=JWT, public=["GET /health"], scopes={"POST /orders": ["orders:write"]})
    auth = api.resources["OrdersAuthorizer"]["Properties"]
    assert auth["AuthorizerType"] == "JWT"
    assert auth["IdentitySource"] == ["$request.header.Authorization"]
    assert auth["JwtConfiguration"] == {"Issuer": ISSUER, "Audience": ["client-1"]}
    routes = {r["Properties"]["RouteKey"]: r["Properties"] for r in api.resources.values() if r["Type"] == "AWS::ApiGatewayV2::Route"}
    assert routes["GET /orders"]["AuthorizationType"] == "JWT" and routes["GET /orders"]["AuthorizerId"] == ref("OrdersAuthorizer")
    assert "AuthorizationScopes" not in routes["GET /orders"]
    assert routes["POST /orders"]["AuthorizationScopes"] == ["orders:write"]
    assert "AuthorizationType" not in routes["GET /health"] and "AuthorizerId" not in routes["GET /health"]
    assert_template_ok(template)


def test_handle_and_wiring() -> None:
    api, _ = stack(cors_origins=["https://app.example.com"], tags={"Stage": "dev"})
    assert api.api_id == ref("OrdersApi") and api.endpoint == get_att("OrdersApi", "ApiEndpoint")
    assert prop(api.resources["OrdersApi"], "CorsConfiguration.AllowOrigins") == ["https://app.example.com"]
    assert prop(api.resources["OrdersApi"], "Tags") == {"Stage": "dev"}
    assert prop(api.resources["OrdersIntegration"], "IntegrationUri") == get_att("Handler", "Arn")
    assert prop(api.resources["OrdersStage"], "StageName") == "$default"
    assert "${OrdersApi}" in prop(api.resources["OrdersInvokePermission"], "SourceArn")


def test_mistakes_are_refused() -> None:
    with pytest.raises(ValueError, match="not routes"):
        http_api("A", function="F", routes=["GET /a"], jwt=JWT, public=["GET /b"])
    with pytest.raises(ValueError, match="only mean something with `jwt`"):
        http_api("A", function="F", routes=["GET /a"], public=["GET /a"])
