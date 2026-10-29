# One load balancer, several ports

The previous page built the pieces. Real stacks repeat them: one load balancer
listening on several ports, each forwarding to its own target group. Only the port
changes, so the repetition belongs in a function that returns a **fragment**.

```python
--8<-- "examples/loadbalancer.py:web_entrypoint"
```

```python
web_entrypoint(
    "Web",
    vpc_id=vpc_id,
    subnets=private_subnets,
    ports=[8080, 9090],
    allowed_cidrs=["10.0.0.0/8"],
    scheme="internal",
)
```

creates these logical IDs ([the rendered YAML](../rendered/web-stack.md) shows the full stack):

| Logical ID | Resource |
|---|---|
| `WebSecurityGroup` | the load balancer's security group |
| `WebLoadBalancer` | the application load balancer |
| `WebTargetGroup8080`, `WebTargetGroup9090` | one target group per port |
| `WebListener8080`, `WebListener9090` | one listener per port |

## Choices worth noticing

- **`allowed_cidrs` has no default.** A default of `0.0.0.0/0` would be convenient and
  would silently expose every internal load balancer someone forgot to restrict. Making
  the caller write it down is a cheap safeguard.
- **Everything the fragment creates refers only to itself.** `vpc_id` and `subnets` come
  in as arguments (literals, parameters or imports), and every `Ref` inside points at
  another resource in the fragment. The tests check exactly that, so a fragment can be
  moved between stacks.
- **`redirect_http=True`** opens port 80 and adds `{name}HttpRedirect`. It insists on a
  certificate, and on port 80 not already being forwarded somewhere, because the other
  combinations are mistakes. An error at generation time beats a surprise at deploy.
- **A loop, not a template.** The per-port resources come from an ordinary `for` loop.
  There is no template language to learn, and the loop body is type-checked.

## Attaching the backend

The Auto Scaling group (or service) that receives the traffic names the target groups
it registers with, and lets the load balancer's group in:

```python
resources = combine(
    web_entrypoint("Web", vpc_id=vpc_id, subnets=subnets, ports=[8080],
                   allowed_cidrs=["10.0.0.0/8"], scheme="internal"),
    {
        "AppAccess": allow_from("AppSecurityGroup", "WebSecurityGroup", 8080),
        # the group's TargetGroupARNs=[ref("WebTargetGroup8080")] connects the two
    },
)
```

[`combine`](composing.md) guards against two fragments reusing a logical ID, which is
the mistake most likely once a stack is built from several of these.
