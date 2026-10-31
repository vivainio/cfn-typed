"""One stack that uses every pattern of integrations.py, so the book's wiring is rendered, checked and linted as a whole."""

import cfn_typed as cfn
from cfn_types import elasticloadbalancingv2 as elbv2
from cfn_types import lambda_, s3, sns
from integrations import (
    alias_to_distribution, alias_to_load_balancer, api_to_dynamodb, api_to_lambda, bucket_to_lambda, event_to_lambda,
    event_to_queue, fan_out, fargate_task, firehose_to_s3, lambda_behind_alb, static_site, stream_trigger, with_stream,
)
from cfn_typed_sumo.patterns import lambda_role, queue_with_dlq
from storage import dynamodb_table


def build() -> cfn.Template:
    params = cfn.Params()
    zone_id = params.string("ZoneId", type="AWS::Route53::HostedZone::Id", description="Hosted zone for the DNS aliases")
    image = params.string("WorkerImage", description="Container image of the worker")
    subnets = params.list_of("Subnets", type="AWS::EC2::Subnet::Id", description="Subnets of the load balancer and the worker")
    group = params.string("WorkerSecurityGroup", type="AWS::EC2::SecurityGroup::Id", description="Security group of the worker")

    orders = with_stream(dynamodb_table("pk", deletion_protection=False))
    changes = stream_trigger("Changes", "Processor", "Orders")
    inbox = queue_with_dlq("Inbox")

    resources = cfn.combine(
        {
            "Orders": orders,
            "Role": lambda_role("processor", changes.statements),
            "Processor": lambda_.function(
                Code={"ZipFile": "def handler(event, context):\n    return {'statusCode': 200, 'body': 'ok'}\n"},
                Handler="index.handler",
                Role=cfn.get_att("Role", "Arn"),
                Runtime="python3.13",
            ),
            "LoadBalancer": elbv2.load_balancer(Type="application", Subnets=subnets),
            "Listener": elbv2.listener(
                LoadBalancerArn=cfn.ref("LoadBalancer"), Port=80, Protocol="HTTP",
                DefaultActions=[{"Type": "fixed-response", "FixedResponseConfig": {"StatusCode": "404"}}],
            ),
            "Lake": s3.bucket(),
        },
        inbox,
        changes.resources,
        static_site("Site"),
        api_to_lambda("Web", "Processor"),
        api_to_dynamodb("Lookup", "Orders"),
        lambda_behind_alb("Api", "Processor", listener="Listener", target_group_name="api-processor", path_pattern="/api/*", priority=10),
        alias_to_load_balancer("ApiDns", zone_id=zone_id, record="api.example.com", load_balancer="LoadBalancer"),
        alias_to_distribution("SiteDns", zone_id=zone_id, record="www.example.com", distribution="SiteDistribution"),
        fan_out("Notice", ["Billing", "Shipping"]),
        event_to_lambda("Nightly", "Processor", schedule="cron(0 2 * * ? *)"),
        event_to_queue("Created", inbox.queue, pattern={"source": ["shop"], "detail-type": ["OrderCreated"]}),
        bucket_to_lambda("Uploads", "Processor", bucket_name="acme-uploads"),
        firehose_to_s3("Events", bucket_arn=cfn.get_att("Lake", "Arn")),
        fargate_task("Worker", image=image, subnets=subnets, security_groups=[group]).resources,
    )
    return {"AWSTemplateFormatVersion": "2010-09-09", "Parameters": params.declarations(), "Resources": resources}


if __name__ == "__main__":
    print(cfn.to_yaml(build()))
