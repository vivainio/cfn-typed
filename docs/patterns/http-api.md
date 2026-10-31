# HTTP API with a JWT authorizer

An API Gateway **HTTP API** in front of a Lambda, with every route behind a JWT authorizer (Cognito or any OIDC
issuer) except the ones you mark public. It is one function, `http_api`, from `cfn-typed-sumo`, and it returns a
handle like [the queue pattern](queue-with-dlq.md) does.

```python
--8<-- "packages/sumo/src/cfn_typed_sumo/http_api.py:http_api"
```

```python
from cfn_typed_sumo import Jwt, http_api

api = http_api(
    "Orders",
    function="Handler",                              # the logical ID of a Lambda in the template
    routes=["GET /orders", "POST /orders", "GET /health"],
    jwt=Jwt(issuer="https://cognito-idp.eu-west-1.amazonaws.com/eu-west-1_abc", audience=["my-client-id"]),
    public=["GET /health"],                          # everything else needs a token
    scopes={"POST /orders": ["orders:write"]},
)
template = {"Resources": cfn.combine({"Handler": handler, "Role": role}, api)}
api.endpoint    # GetAtt OrdersApi.ApiEndpoint, for an output or a DNS record
```

## Things worth noticing

- **Secure by default.** With `jwt`, a route is protected unless you list it in `public`. Forgetting a route
  protects it, never exposes it. Without `jwt` nothing is authorized, and the pattern adds no authorizer.
- **Mistakes are refused when the template is built.** A `public` or `scopes` entry that is not one of `routes`
  (a typo, so the route stays protected or loses its scope) raises, and so does `public` or `scopes` without `jwt`.
- **The invoke permission is part of it.** Without the `AWS::Lambda::Permission`, API Gateway answers 500 and nothing
  in the template says why. `SourceArn` is scoped to this API.
- **`AutoDeploy`.** The stage is `$default` with auto-deploy, so a changed route is live without a deployment
  resource, unlike the [REST API pattern](web-frontends.md#a-rest-api-in-front-of-a-lambda).
- **Route logical IDs come from the route key**: `GET /orders/{id}` becomes `OrdersRouteGetOrdersId`.
- **Tags are a mapping** here (an HTTP API takes `Tags: {key: value}`, not the list the other patterns use).
- **The audience is the client ID** for Cognito access tokens' `client_id` and ID tokens' `aud`; for other
  issuers use whatever the `aud` claim carries.
