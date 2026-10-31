# Mandatory tags

A company defines the tags every resource must carry. Each service then supplies them: some for all its
resources, some per resource. The pattern checks that the pieces add up to the full set.

```python
--8<-- "packages/sumo/src/cfn_typed_sumo/patterns.py:company_tags"
```

```python
service: SomeCompanyTags = {"owner": "team-orders", "cost_center": "CC-1234", "environment": "prod", "role": "queue"}
resources = tagged(queue_with_dlq("Order", tags=tags(role="dlq")).resources, service)
# OrderQueue gets role=queue from the service, OrderDLQ overrides it with role=dlq
```

## Three layers

| Layer | Where it lives | What it is |
|---|---|---|
| Company | `CompanyTags` | the complete, required set, with validation |
| Service | `SomeCompanyTags`, passed to `tagged` | any subset, applied to every resource |
| Resource | the resource's own `Tags` | any subset, overriding the service for that resource |

Resource beats service. After merging, each taggable resource must have every company tag, or `tagged` raises
`OrderDLQ is missing company tags: cost_center, environment, role`. The merged values are then built as a
`CompanyTags`, so the format checks run on them too. The type checker rejects a service tag the company did not define. Other tags on a resource (an `Extra`, say) are
left alone.

## Things worth noticing

- **The dataclass is the policy.** Every field is required and keyword-only. Adding a required tag is one new
  field, and `REQUIRED` and the checks follow it. `SomeCompanyTags` repeats the field names as a `TypedDict`, so a
  service's tags are type-checked against them; keep the two in step.
- **Completeness is checked per resource, after merging.** A service may leave out `role` as long as every
  resource sets its own. A service that gives everything needs no per-resource tags at all.
- **The taggable set is a decision.** `TAGGABLE` lists the types the company expects tags on. Tags are
  shaped differently per resource type, so this example covers the common `Tags` list only.
- **Values must be literals.** The merged tags are validated as strings, so a `Ref` in a company tag is not
  supported by this example.
- **`untagged` is the backstop.** Run it before deploying, or in a test, for templates that skip `tagged`.
  It only checks what is in the template. To enforce the policy against people who do not use this code at all,
  add an AWS Config `required-tags` rule or a CloudFormation Hook.
