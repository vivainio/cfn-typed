import cfn_typed as cfn


def test_merge_is_deep() -> None:
    base = {"Environment": {"Variables": {"A": "1", "B": "2"}}, "Timeout": 30}
    override = {"Environment": {"Variables": {"B": "3"}}, "Timeout": 60}
    assert cfn.merge(base, override) == {"Environment": {"Variables": {"A": "1", "B": "3"}}, "Timeout": 60}
    assert (base | override)["Environment"] == {"Variables": {"B": "3"}}  # the shallow behaviour merge() fixes
    assert base["Environment"]["Variables"] == {"A": "1", "B": "2"}  # inputs are not mutated


def test_allow_builds_a_statement() -> None:
    assert cfn.allow(cfn.SQS_CONSUME, [cfn.get_att("Q", "Arn")])["Effect"] == "Allow"
