"""A stand-in for a private "defaults" package: shared settings exposed as variables."""

# --8<-- [start:defaults]
from typing import NamedTuple

from cfn_typed import Expr, Params, Tag
from cfn_typed.intrinsics import Ref


class Network(NamedTuple):
    vpc_id: Ref
    private_subnets: Ref


def network(params: Params) -> Network:
    """The shared network, read from SSM by CloudFormation at deploy time."""
    return Network(
        vpc_id=params.ssm("VpcId", "/platform/network/vpc-id", description="Shared VPC"),
        private_subnets=params.ssm_list("PrivateSubnets", "/platform/network/private-subnets"),
    )


def standard_tags(params: Params) -> list[Expr[Tag]]:
    stage = params.string("Stage", default="dev", allowed_values=["dev", "test", "prod"])
    return [{"Key": "Stage", "Value": stage}, {"Key": "ManagedBy", "Value": "cfn-typed"}]
# --8<-- [end:defaults]
