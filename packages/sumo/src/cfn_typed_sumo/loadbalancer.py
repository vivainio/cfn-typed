"""Application load balancer patterns shown in the book (docs/patterns/load-balancer.md)."""

# --8<-- [start:imports]
from collections.abc import Sequence
from typing import Literal

from cfn_typed_sumo.types import ec2
from cfn_typed_sumo.types import elasticloadbalancingv2 as elbv2

from cfn_typed import Expr, Resources, Tag, ref

# --8<-- [end:imports]


# --8<-- [start:load_balancer]
def load_balancer(
    *,
    subnets: Expr[list[Expr[str]]],
    security_groups: list[Expr[str]],
    scheme: Literal["internet-facing", "internal"] = "internet-facing",
    idle_timeout: int = 60,
    tags: list[Expr[Tag]] | None = None,
) -> elbv2.LoadBalancer:
    """An application load balancer. No `Name`, so CloudFormation picks a unique one."""
    props: elbv2.LoadBalancerProps = {
        "Type": "application",
        "Scheme": scheme,
        "Subnets": subnets,
        "SecurityGroups": security_groups,
        "LoadBalancerAttributes": [{"Key": "idle_timeout.timeout_seconds", "Value": str(idle_timeout)}],
    }
    if tags:
        props["Tags"] = tags
    return elbv2.load_balancer(**props)
# --8<-- [end:load_balancer]


# --8<-- [start:target_group]
def target_group(
    *,
    vpc_id: Expr[str],
    port: int,
    protocol: Literal["HTTP", "HTTPS"] = "HTTP",
    health_check_path: str = "/",
    health_check_port: str = "traffic-port",
    deregistration_delay: int = 30,
    target_type: Literal["instance", "ip", "lambda"] = "instance",
    tags: list[Expr[Tag]] | None = None,
) -> elbv2.TargetGroup:
    """Where the traffic goes. A short deregistration delay makes deploys faster."""
    props: elbv2.TargetGroupProps = {
        "VpcId": vpc_id,
        "Port": port,
        "Protocol": protocol,
        "TargetType": target_type,
        "HealthCheckEnabled": True,
        "HealthCheckPath": health_check_path,
        "HealthCheckPort": health_check_port,
        "HealthyThresholdCount": 2,
        "TargetGroupAttributes": [
            {"Key": "deregistration_delay.timeout_seconds", "Value": str(deregistration_delay)},
        ],
    }
    if tags:
        props["Tags"] = tags
    return elbv2.target_group(**props)
# --8<-- [end:target_group]


# --8<-- [start:listener]
def listener(
    *,
    load_balancer: str,
    target_group: str,
    port: int,
    certificate_arn: Expr[str] | None = None,
) -> elbv2.Listener:
    """Forward a port to a target group. A certificate turns it into an HTTPS listener."""
    props: elbv2.ListenerProps = {
        "LoadBalancerArn": ref(load_balancer),
        "Port": port,
        "Protocol": "HTTPS" if certificate_arn else "HTTP",
        "DefaultActions": [{"Type": "forward", "TargetGroupArn": ref(target_group)}],
    }
    if certificate_arn:
        props["Certificates"] = [{"CertificateArn": certificate_arn}]
        props["SslPolicy"] = "ELBSecurityPolicy-TLS13-1-2-2021-06"
    return elbv2.listener(**props)


def redirect_http_to_https(load_balancer: str, *, port: int = 80, to_port: int = 443) -> elbv2.Listener:
    """A listener that answers with a permanent redirect instead of forwarding."""
    return elbv2.listener(
        LoadBalancerArn=ref(load_balancer),
        Port=port,
        Protocol="HTTP",
        DefaultActions=[{
            "Type": "redirect",
            "RedirectConfig": {"Protocol": "HTTPS", "Port": str(to_port), "StatusCode": "HTTP_301"},
        }],
    )
# --8<-- [end:listener]


# --8<-- [start:allow_from]
def allow_from(group: str, source_group: str, port: int) -> ec2.SecurityGroupIngress:
    """Let `source_group` (the load balancer's) reach `group` (the instances') on `port`."""
    return ec2.security_group_ingress(
        GroupId=ref(group),
        SourceSecurityGroupId=ref(source_group),
        IpProtocol="tcp",
        FromPort=port,
        ToPort=port,
    )
# --8<-- [end:allow_from]


# --8<-- [start:web_entrypoint]
def web_entrypoint(
    name: str,
    *,
    vpc_id: Expr[str],
    subnets: Expr[list[Expr[str]]],
    ports: Sequence[int],
    allowed_cidrs: Sequence[str],
    scheme: Literal["internet-facing", "internal"] = "internet-facing",
    certificate_arn: Expr[str] | None = None,
    redirect_http: bool = False,
    health_check_path: str = "/",
    tags: list[Expr[Tag]] | None = None,
) -> Resources:
    """One load balancer in front of several ports.

    Logical IDs: `{name}SecurityGroup`, `{name}LoadBalancer`, and per port `p`
    `{name}TargetGroup{p}` and `{name}Listener{p}`. With `redirect_http`, port 80 is opened and
    answered by `{name}HttpRedirect`.
    """
    if redirect_http and (certificate_arn is None or 80 in ports):
        raise ValueError("redirect_http needs a certificate_arn and no forwarded port 80")
    open_ports = [*ports, 80] if redirect_http else list(ports)
    group, lb = f"{name}SecurityGroup", f"{name}LoadBalancer"
    ingress: list[Expr[ec2.SecurityGroupIngressProperty]] = [
        {"IpProtocol": "tcp", "FromPort": p, "ToPort": p, "CidrIp": cidr}
        for p in open_ports
        for cidr in allowed_cidrs
    ]
    resources: Resources = {
        group: ec2.security_group(
            GroupDescription=f"{name} load balancer",
            VpcId=vpc_id,
            SecurityGroupIngress=ingress,
        ),
        lb: load_balancer(subnets=subnets, security_groups=[ref(group)], scheme=scheme, tags=tags),
    }
    for p in ports:
        tg = f"{name}TargetGroup{p}"
        resources[tg] = target_group(vpc_id=vpc_id, port=p, health_check_path=health_check_path, tags=tags)
        resources[f"{name}Listener{p}"] = listener(
            load_balancer=lb, target_group=tg, port=p, certificate_arn=certificate_arn,
        )
    if redirect_http:
        resources[f"{name}HttpRedirect"] = redirect_http_to_https(lb)
    return resources
# --8<-- [end:web_entrypoint]
