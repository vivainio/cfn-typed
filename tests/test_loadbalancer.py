import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent / "examples"))

from cfn_typed_sumo.loadbalancer import allow_from, redirect_http_to_https, web_entrypoint  # noqa: E402

from cfn_typed import ref  # noqa: E402



def plain(value: Any) -> Any:
    """What CloudFormation would see: tests inspect the rendered JSON, not the typed structure."""
    return json.loads(json.dumps(value))


FRAGMENT = plain(web_entrypoint(
    "Web",
    vpc_id="vpc-123",
    subnets=["subnet-a", "subnet-b"],
    ports=[8080, 9090],
    allowed_cidrs=["10.0.0.0/8"],
    scheme="internal",
))


def refs(node: object) -> set[str]:
    """Every `Ref` target in a JSON-like structure."""
    if isinstance(node, dict):
        found = {node["Ref"]} if set(node) == {"Ref"} else set()
        return found.union(*(refs(v) for v in node.values()))
    if isinstance(node, list):
        return set().union(*(refs(v) for v in node))
    return set()


def test_one_pair_per_port() -> None:
    assert set(FRAGMENT) == {
        "WebSecurityGroup", "WebLoadBalancer",
        "WebTargetGroup8080", "WebListener8080", "WebTargetGroup9090", "WebListener9090",
    }
    lb = FRAGMENT["WebLoadBalancer"]["Properties"]
    assert lb["Scheme"] == "internal" and lb["Type"] == "application"
    assert "Name" not in lb  # CloudFormation chooses a unique name


def test_every_ref_resolves_inside_the_fragment() -> None:
    assert refs(FRAGMENT) <= set(FRAGMENT)


def test_security_group_opens_only_the_listener_ports_to_the_given_cidrs() -> None:
    rules = FRAGMENT["WebSecurityGroup"]["Properties"]["SecurityGroupIngress"]
    assert {(r["FromPort"], r["CidrIp"]) for r in rules} == {(8080, "10.0.0.0/8"), (9090, "10.0.0.0/8")}


def test_certificate_turns_listeners_into_https() -> None:
    frag = plain(web_entrypoint(
        "Web", vpc_id="v", subnets=["s"], ports=[443], allowed_cidrs=["0.0.0.0/0"], certificate_arn="arn:cert",
    ))
    props = frag["WebListener443"]["Properties"]
    assert props["Protocol"] == "HTTPS"
    assert props["Certificates"] == [{"CertificateArn": "arn:cert"}]
    assert "Certificates" not in FRAGMENT["WebListener8080"]["Properties"]


def test_redirect_and_allow_from() -> None:
    action = plain(redirect_http_to_https("Lb"))["Properties"]["DefaultActions"][0]
    assert action["Type"] == "redirect" and action["RedirectConfig"]["StatusCode"] == "HTTP_301"
    rule = plain(allow_from("AppSg", "LbSg", 8080))["Properties"]
    assert rule["GroupId"] == plain(ref("AppSg")) and rule["SourceSecurityGroupId"] == plain(ref("LbSg"))


def test_redirect_http_opens_port_80_and_answers_it() -> None:
    import pytest

    frag = plain(web_entrypoint(
        "Web", vpc_id="v", subnets=["s"], ports=[443], allowed_cidrs=["10.0.0.0/8"],
        certificate_arn="arn:cert", redirect_http=True,
    ))
    rules = frag["WebSecurityGroup"]["Properties"]["SecurityGroupIngress"]
    assert {r["FromPort"] for r in rules} == {443, 80}
    assert frag["WebHttpRedirect"]["Properties"]["DefaultActions"][0]["Type"] == "redirect"
    assert refs(frag) <= set(frag)
    with pytest.raises(ValueError):
        web_entrypoint("Web", vpc_id="v", subnets=["s"], ports=[443], allowed_cidrs=["x"], redirect_http=True)
    with pytest.raises(ValueError):
        web_entrypoint("Web", vpc_id="v", subnets=["s"], ports=[80], allowed_cidrs=["x"],
                       certificate_arn="c", redirect_http=True)
