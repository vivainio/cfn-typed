# Fargate tasks

A worker, or a task that a Lambda starts on demand, in the style of the Solutions Constructs `lambda-fargate`
pattern. For a web service with a load balancer see `fargate_service` in [CDK L2 constructs](cdk-l2.md): this one
has none.

```python
--8<-- "examples/integrations.py:imports"
```

```python
--8<-- "examples/integrations.py:fargate_task"
```

```python
job = fargate_task(
    "Report", image=ref("ReportImage"), subnets=ref("PrivateSubnets"), security_groups=[ref("TaskGroup")],
    desired_count=None,                                    # started on demand, no service
    task_statements=[allow("s3:PutObject", arn.object("reports"))],
)
starter = lambda_role("starter", job.run_task_statements)  # and pass job.environment to the function
```

## Things worth noticing

- **Two roles, and they are not interchangeable.** The *execution role* is what ECS uses to pull the image and
  write logs. The *task role* is what your code runs as, so `task_statements` go there. Putting application
  permissions on the execution role is the usual mistake, and a role for both is too much for each.
- **A Lambda that starts tasks needs `iam:PassRole`** for both roles, on top of `ecs:RunTask`.
  `run_task_statements` has both, and `RunTask` is limited to this cluster.
- **The invoker learns where to run from the template.** `environment` gives the cluster, task definition,
  subnets and security group as values, so none is a string copied into code.
- **No public IP.** Tasks sit in private subnets. They need a NAT gateway or VPC endpoints to pull the image.
- **A circuit breaker with rollback** is on, so a bad image rolls back instead of restarting forever.
