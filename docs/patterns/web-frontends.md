# Web frontends

The same idea as the AWS Solutions Constructs `cloudfront-s3`, `apigateway-lambda`, `apigateway-dynamodb`,
`alb-lambda` and `route53-*` patterns: *A in front of B*, including the permission that makes the connection work.
The static site is in `cfn-typed-sumo` (`from cfn_typed_sumo import static_site`); the rest are pulled from
[`examples/integrations.py`](https://github.com/vivainio/cfn-typed/blob/main/examples/integrations.py).

```python
--8<-- "examples/integrations.py:imports"
```

## A static site

```python
--8<-- "packages/sumo/src/cfn_typed_sumo/static_site.py:static_site"
```

- **The bucket stays private.** CloudFront reads it with *origin access control*, and the bucket policy allows
  only the `cloudfront.amazonaws.com` service, and only for **this** distribution (`aws:SourceArn`). Another
  account's distribution cannot read the bucket, even if it knows the name.
- **`S3OriginConfig` is empty on purpose.** The property is still required for an S3 origin. The old origin access
  identity is what used to go in it, and OAC replaces that.
- **No cycle.** The policy refers to the distribution, and the distribution to the bucket, never the other way.
- **A domain and certificate are optional.** `domain=SiteDomain(["www.example.com"], hosted_zone_id=...)` has the
  stack request an ACM certificate, validate it by DNS in that hosted zone, and put the names and the certificate on
  the distribution (SNI, TLS 1.2 minimum). `SiteDomain(names, certificate_arn=...)` uses a certificate you already
  have. Exactly one of the two is required. **CloudFront only takes certificates from us-east-1**, so a stack that
  creates one has to be deployed there; if yours is elsewhere, make the certificate in a us-east-1 stack and pass its
  ARN. The DNS records for the names are [the alias pattern below](#dns-names).
- **SSE-S3, not a KMS key.** With a customer-managed key the key policy would need a statement for CloudFront too.

## A REST API in front of a Lambda

```python
--8<-- "examples/integrations.py:rest_api_deploy"
```

```python
--8<-- "examples/integrations.py:api_lambda"
```

- **Two methods.** `{proxy+}` does not match the root path, so `/` needs a method of its own.
- **The permission is the part people forget.** Without it API Gateway answers 500, and nothing in the
  template says why. `SourceArn` ends in `/*/*/*` (stage, method, path), so it covers every route of this API
  and no other.
- **The deployment lists its methods in `DependsOn`.** CloudFormation does not know that a deployment is a snapshot
  of the methods, so without it the first deploy can snapshot an empty API. `_deploy` is shared with the next pattern.
- **Changing a method later does not redeploy.** A deployment is created once; redeploy by changing its logical
  ID (add a version to the name) or with a hash of the API definition in `Description`.

## A REST API straight to DynamoDB

```python
--8<-- "examples/integrations.py:api_dynamodb"
```

`GET /items/{id}` calls `GetItem` itself, with no function in between. The role may do exactly one thing, read this
table, and the request template turns the path parameter into the DynamoDB call. The key name is an argument
(`key="pk"`), and the table is named by its logical ID, so the policy and the template follow the table when it is
renamed. For anything beyond a lookup, put a Lambda behind the API instead.

## A Lambda behind a load balancer

```python
--8<-- "examples/integrations.py:alb_lambda"
```

This one has a trap worth knowing. The target group must wait for the permission, or registering the function
fails. The permission would normally name the target group (`SourceArn: !Ref TargetGroup`), which closes a cycle,
and `assert_references_resolve` says so. The way out is to **name the target group yourself** and build its ARN in
the permission with a wildcard for the id suffix. The Solutions Constructs pattern, and the CDK, hide this
choice. The listener is the one from [load balancer building blocks](load-balancer.md).

## DNS names

```python
--8<-- "examples/integrations.py:route53_alias"
```

An alias record has no TTL, costs nothing to query, and works at the zone apex, which a `CNAME` cannot. The hosted
zone id in `AliasTarget` is the **target's** zone, not yours: the load balancer reports its own
(`CanonicalHostedZoneID`), and every CloudFront distribution uses the same constant.
