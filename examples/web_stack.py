"""A stack that takes its network and tags from the defaults, as parameters."""

import cfn_typed as cfn
from defaults import network, standard_tags
from cfn_typed_sumo.loadbalancer import web_entrypoint


# --8<-- [start:stack]
def build() -> cfn.Template:
    params = cfn.Params()
    net = network(params)  # only what is called gets declared
    tags = standard_tags(params)
    return {
        "AWSTemplateFormatVersion": "2010-09-09",
        "Parameters": params.declarations(),
        "Resources": web_entrypoint(
            "Web",
            vpc_id=net.vpc_id,
            subnets=net.private_subnets,
            ports=[8080],
            allowed_cidrs=["10.0.0.0/8"],
            scheme="internal",
            tags=tags,
        ),
    }
# --8<-- [end:stack]


if __name__ == "__main__":
    print(cfn.to_yaml(build()))
