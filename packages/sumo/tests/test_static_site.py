import pytest

from cfn_typed_sumo import SiteDomain, static_site

from cfn_typed import ref
from cfn_typed.query import prop
from cfn_typed.testing import assert_template_ok

ARN = "arn:aws:acm:us-east-1:123456789012:certificate/abc"


def config(res):
    return res["SiteDistribution"]["Properties"]["DistributionConfig"]


def test_default_site_has_no_domain_or_certificate() -> None:
    res = static_site("Site")
    assert set(res) == {"SiteBucket", "SiteOAC", "SiteDistribution", "SiteBucketPolicy"}
    assert "Aliases" not in config(res) and "ViewerCertificate" not in config(res)
    assert_template_ok({"Resources": res})


def test_domain_with_an_existing_certificate() -> None:
    res = static_site("Site", domain=SiteDomain(["www.example.com"], certificate_arn=ARN))
    assert "SiteCertificate" not in res
    assert config(res)["Aliases"] == ["www.example.com"]
    assert config(res)["ViewerCertificate"] == {"AcmCertificateArn": ARN, "SslSupportMethod": "sni-only", "MinimumProtocolVersion": "TLSv1.2_2021"}
    assert_template_ok({"Resources": res})


def test_domain_requests_a_dns_validated_certificate() -> None:
    res = static_site("Site", domain=SiteDomain(["example.com", "www.example.com"], hosted_zone_id="Z123"))
    cert = res["SiteCertificate"]["Properties"]
    assert cert["DomainName"] == "example.com" and cert["SubjectAlternativeNames"] == ["www.example.com"]
    assert cert["ValidationMethod"] == "DNS"
    assert cert["DomainValidationOptions"] == [{"DomainName": n, "HostedZoneId": "Z123"} for n in ("example.com", "www.example.com")]
    assert prop(res["SiteDistribution"], "DistributionConfig.ViewerCertificate.AcmCertificateArn") == ref("SiteCertificate")
    assert_template_ok({"Resources": res})


def test_single_name_has_no_alternative_names() -> None:
    res = static_site("Site", domain=SiteDomain(["example.com"], hosted_zone_id="Z123"))
    assert "SubjectAlternativeNames" not in res["SiteCertificate"]["Properties"]


def test_a_domain_needs_exactly_one_certificate_source() -> None:
    with pytest.raises(ValueError, match="either certificate_arn"):
        SiteDomain(["example.com"])
    with pytest.raises(ValueError, match="either certificate_arn"):
        SiteDomain(["example.com"], certificate_arn=ARN, hosted_zone_id="Z1")
    with pytest.raises(ValueError, match="at least one name"):
        SiteDomain([], hosted_zone_id="Z1")
