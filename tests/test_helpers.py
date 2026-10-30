from pathlib import Path

import pytest

import cfn_typed as cfn


def test_merge_is_deep() -> None:
    base = {"Environment": {"Variables": {"A": "1", "B": "2"}}, "Timeout": 30}
    override = {"Environment": {"Variables": {"B": "3"}}, "Timeout": 60}
    assert cfn.merge(base, override) == {"Environment": {"Variables": {"A": "1", "B": "3"}}, "Timeout": 60}
    assert (base | override)["Environment"] == {"Variables": {"B": "3"}}  # the shallow behaviour merge() fixes
    assert base["Environment"]["Variables"] == {"A": "1", "B": "2"}  # inputs are not mutated


def test_allow_builds_a_statement() -> None:
    assert cfn.allow(["sqs:ReceiveMessage"], [cfn.get_att("Q", "Arn")])["Effect"] == "Allow"


def arn_text(service: str, resource: str, *, region: bool | str | None = None, account: bool | str | None = None) -> str:
    template = cfn.arn(service, resource, region=region, account=account)["Fn::Sub"]
    assert isinstance(template, str)
    return template


def test_arn_knows_which_arns_have_no_region_or_account() -> None:
    assert arn_text("dynamodb", "table/t") == "arn:${AWS::Partition}:dynamodb:${AWS::Region}:${AWS::AccountId}:table/t"
    assert arn_text("s3", "my-bucket/*") == "arn:${AWS::Partition}:s3:::my-bucket/*"  # no region, no account
    assert arn_text("iam", "role/r") == "arn:${AWS::Partition}:iam::${AWS::AccountId}:role/r"  # no region
    assert arn_text("s3", "accesspoint/ap") == "arn:${AWS::Partition}:s3:${AWS::Region}:${AWS::AccountId}:accesspoint/ap"


def test_arn_can_be_told_explicitly() -> None:
    assert arn_text("route53", "hostedzone/Z", region=False) == "arn:${AWS::Partition}:route53::${AWS::AccountId}:hostedzone/Z"
    assert arn_text("sns", "t", account=False) == "arn:${AWS::Partition}:sns:${AWS::Region}::t"


def test_arn_can_name_another_region_or_account() -> None:
    assert arn_text("sns", "t", account="111111111111", region="eu-west-1") == "arn:${AWS::Partition}:sns:eu-west-1:111111111111:t"


def test_arn_has_a_method_for_each_resource_kind() -> None:
    p, r, a = "arn:${AWS::Partition}", "${AWS::Region}", "${AWS::AccountId}"
    expected = [
        (cfn.arn.bucket("data"), f"{p}:s3:::data"),
        (cfn.arn.object("data"), f"{p}:s3:::data/*"),
        (cfn.arn.object("data", "in/*"), f"{p}:s3:::data/in/*"),
        (cfn.arn.function("f"), f"{p}:lambda:{r}:{a}:function:f"),
        (cfn.arn.function("f", "live"), f"{p}:lambda:{r}:{a}:function:f:live"),
        (cfn.arn.table("t"), f"{p}:dynamodb:{r}:{a}:table/t"),
        (cfn.arn.table_index("t", "i"), f"{p}:dynamodb:{r}:{a}:table/t/index/i"),
        (cfn.arn.queue("q"), f"{p}:sqs:{r}:{a}:q"),
        (cfn.arn.topic("n"), f"{p}:sns:{r}:{a}:n"),
        (cfn.arn.role("x"), f"{p}:iam::{a}:role/x"),
        (cfn.arn.role("x", "/svc/"), f"{p}:iam::{a}:role/svc/x"),
        (cfn.arn.policy("x"), f"{p}:iam::{a}:policy/x"),
        (cfn.arn.secret("s-*"), f"{p}:secretsmanager:{r}:{a}:secret:s-*"),
        (cfn.arn.parameter("/p/k"), f"{p}:ssm:{r}:{a}:parameter/p/k"),
        (cfn.arn.log_group("/g", streams=True), f"{p}:logs:{r}:{a}:log-group:/g:*"),
        (cfn.arn.key("k"), f"{p}:kms:{r}:{a}:key/k"),
    ]
    for built, text in expected:
        assert built == {"Fn::Sub": text}


def test_combine_takes_dicts_and_handles_and_rejects_duplicates() -> None:
    class Handle:
        resources: cfn.Resources = {"B": {"Type": "AWS::SQS::Queue"}}

    queue: cfn.Resources = {"A": {"Type": "AWS::SQS::Queue"}}
    assert set(cfn.combine(queue, Handle())) == {"A", "B"}
    with pytest.raises(ValueError, match="B"):
        cfn.combine(Handle(), Handle().resources)


def test_core_page_lists_every_export() -> None:
    page = (Path(__file__).parent.parent / "docs" / "core.md").read_text()
    missing = [name for name in cfn.__all__ if f"`{name}`" not in page]
    assert not missing, f"docs/core.md does not mention: {', '.join(missing)}"
