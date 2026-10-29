import cfn_typed as cfn


def test_merge_is_deep() -> None:
    base = {"Environment": {"Variables": {"A": "1", "B": "2"}}, "Timeout": 30}
    override = {"Environment": {"Variables": {"B": "3"}}, "Timeout": 60}
    assert cfn.merge(base, override) == {"Environment": {"Variables": {"A": "1", "B": "3"}}, "Timeout": 60}
    assert (base | override)["Environment"] == {"Variables": {"B": "3"}}  # the shallow behaviour merge() fixes
    assert base["Environment"]["Variables"] == {"A": "1", "B": "2"}  # inputs are not mutated


def test_allow_builds_a_statement() -> None:
    assert cfn.allow(["sqs:ReceiveMessage"], [cfn.get_att("Q", "Arn")])["Effect"] == "Allow"


def arn_text(service: str, resource: str, *, region: bool | None = None, account: bool | None = None) -> str:
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
