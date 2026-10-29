# Load balancer building blocks

An application load balancer is four small resources that always appear together:
the **load balancer**, a **target group** per backend, a **listener** per port that
connects the two, and **security groups** so traffic can flow. Each one has a handful of
properties you set the same way every time, which is what makes them worth wrapping.

These helpers are deliberately thin. They take plain arguments and return one generated
resource, so the type checker still knows exactly what you built.

```python
--8<-- "examples/loadbalancer.py:imports"
```

## The load balancer

```python
--8<-- "examples/loadbalancer.py:load_balancer"
```

- **There is no `Name`.** Leaving it out lets CloudFormation choose a unique one, so a
  replacement can be created before the old load balancer is deleted. A fixed name
  blocks that.
- **`scheme` is a `Literal`.** `"internal"` or `"internet-facing"` autocompletes, and a
  typo such as `"internet_facing"` is an error before deploy.
- **`idle_timeout`** is the one attribute almost everyone changes, so it is an argument
  and the rest stay at their defaults.

## The target group

```python
--8<-- "examples/loadbalancer.py:target_group"
```

The short `deregistration_delay` is a deliberate default. The AWS default of five
minutes makes every deploy wait for connections that will never finish. Raise it for
services with long-lived requests.

## Listeners

```python
--8<-- "examples/loadbalancer.py:listener"
```

- **A certificate decides the protocol.** Passing `certificate_arn` makes the listener
  HTTPS and adds a TLS policy; leaving it out makes plain HTTP. One argument, so the
  two can never disagree.
- **Listeners and target groups are named by logical ID**, not passed as objects. The
  helper turns them into `ref(...)`. That is the same trade-off as everywhere else in
  this book: a short call site, with the name as a string.
- **`redirect_http_to_https`** shows a different default action. The generated
  `ListenerAction` type has a field for each kind of action, and `RedirectConfig` is
  checked like everything else.

## Letting traffic through

```python
--8<-- "examples/loadbalancer.py:allow_from"
```

The instances (or tasks) behind the load balancer should accept traffic **from the load
balancer's security group**, not from an address range. Then it stays correct when the
load balancer's addresses change, and nothing else in the VPC can reach the port.
