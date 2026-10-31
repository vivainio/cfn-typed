"""A private S3 bucket served by CloudFront, optionally on your own domain. Sections feed docs/patterns/web-frontends.md."""

# --8<-- [start:static_site]
from collections.abc import Sequence
from dataclasses import dataclass

from cfn_typed_sumo.types import certificatemanager as acm
from cfn_typed_sumo.types import cloudfront, s3

from cfn_typed import Expr, Resources, Tag, allow, get_att, join, policy_document, ref, sub
from cfn_typed.policy import arn_equals, service

CACHING_OPTIMIZED = "658327ea-f89d-4fab-a63d-7e88639e58f6"  # the managed cache policy of the same name


@dataclass(frozen=True)
class SiteDomain:
    """Serve the site on `names` instead of the `*.cloudfront.net` name.

    Give `certificate_arn` to use an existing certificate, or `hosted_zone_id` to have the stack request one and
    validate it by DNS in that hosted zone. CloudFront only accepts certificates from **us-east-1**, so a stack
    that creates one has to be deployed there. `names` are the domain names; the first is the certificate's.
    """

    names: Sequence[str]
    certificate_arn: Expr[str] | None = None
    hosted_zone_id: Expr[str] | None = None

    def __post_init__(self) -> None:
        if not self.names:
            raise ValueError("a domain needs at least one name")
        if (self.certificate_arn is None) == (self.hosted_zone_id is None):
            raise ValueError("give either certificate_arn (use that certificate) or hosted_zone_id (request one)")


def static_site(
    name: str,
    *,
    default_root_object: str = "index.html",
    domain: SiteDomain | None = None,
    tags: list[Expr[Tag]] | None = None,
) -> Resources:
    """A private bucket served by CloudFront through origin access control (OAC).

    Logical IDs: `{name}Bucket`, `{name}BucketPolicy`, `{name}OAC` and `{name}Distribution`, plus
    `{name}Certificate` when `domain` asks for one. The bucket stays private: only this distribution may read
    it, which the policy states with `aws:SourceArn`.
    """
    bucket, oac, dist, cert = f"{name}Bucket", f"{name}OAC", f"{name}Distribution", f"{name}Certificate"
    bucket_props: s3.BucketProps = {
        "PublicAccessBlockConfiguration": {
            "BlockPublicAcls": True, "BlockPublicPolicy": True, "IgnorePublicAcls": True, "RestrictPublicBuckets": True,
        },
        "BucketEncryption": {"ServerSideEncryptionConfiguration": [{"ServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]},
    }
    config: cloudfront.DistributionDistributionConfig = {
        "Enabled": True,
        "HttpVersion": "http2and3",
        "DefaultRootObject": default_root_object,
        "Origins": [{
            "Id": "site",
            "DomainName": get_att(bucket, "RegionalDomainName"),
            "OriginAccessControlId": get_att(oac, "Id"),
            "S3OriginConfig": {},  # required for an S3 origin; empty because OAC replaces the old identity
        }],
        "DefaultCacheBehavior": {
            "TargetOriginId": "site",
            "ViewerProtocolPolicy": "redirect-to-https",
            "CachePolicyId": CACHING_OPTIMIZED,
            "Compress": True,
        },
    }
    extra: Resources = {}
    if domain:
        certificate_arn: Expr[str]
        if domain.certificate_arn is not None:
            certificate_arn = domain.certificate_arn
        elif domain.hosted_zone_id is not None:
            certificate_arn = ref(cert)
            cert_props: acm.CertificateProps = {
                "DomainName": domain.names[0],
                "ValidationMethod": "DNS",
                "DomainValidationOptions": [{"DomainName": n, "HostedZoneId": domain.hosted_zone_id} for n in domain.names],
            }
            if len(domain.names) > 1:
                cert_props["SubjectAlternativeNames"] = list(domain.names[1:])
            extra[cert] = acm.certificate(**cert_props)
        else:  # SiteDomain refuses this
            raise ValueError("a domain needs a certificate_arn or a hosted_zone_id")
        config["Aliases"] = list(domain.names)
        config["ViewerCertificate"] = {
            "AcmCertificateArn": certificate_arn,
            "SslSupportMethod": "sni-only",
            "MinimumProtocolVersion": "TLSv1.2_2021",
        }
    dist_props: cloudfront.DistributionProps = {"DistributionConfig": config}
    if tags:
        bucket_props["Tags"] = dist_props["Tags"] = tags
    return {
        bucket: s3.bucket(**bucket_props),
        oac: cloudfront.origin_access_control(OriginAccessControlConfig={
            "Name": sub("${AWS::StackName}-" + name),
            "OriginAccessControlOriginType": "s3",
            "SigningBehavior": "always",
            "SigningProtocol": "sigv4",
        }),
        dist: cloudfront.distribution(**dist_props),
        f"{name}BucketPolicy": s3.bucket_policy(
            Bucket=ref(bucket),
            PolicyDocument=policy_document([allow(
                "s3:GetObject", join("", [get_att(bucket, "Arn"), "/*"]),
                sid="AllowCloudFrontRead",
                principal=service("cloudfront.amazonaws.com"),
                condition=arn_equals("aws:SourceArn", sub("arn:${AWS::Partition}:cloudfront::${AWS::AccountId}:distribution/${D}", {"D": ref(dist)})),
            )]),
        ),
        **extra,
    }
# --8<-- [end:static_site]
