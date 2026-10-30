"""`keys` derives the table's key properties; the type promises are checked by running `ty` on code that breaks them."""

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from cfn_typed.dynamodb import gsi, keys, lsi

ROOT = Path(__file__).parent.parent
TY = shutil.which("ty")


def plain(value: Any) -> Any:
    """What CloudFormation would see; the typed result is a union with intrinsics, so tests read the JSON."""
    return json.loads(json.dumps(value))


def test_a_bare_name_is_a_string_and_a_range_key_is_optional() -> None:
    assert plain(keys("id")) == {
        "AttributeDefinitions": [{"AttributeName": "id", "AttributeType": "S"}],
        "KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}],
    }
    both = plain(keys("pk", ("ts", "N")))
    assert both["KeySchema"] == [{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "ts", "KeyType": "RANGE"}]
    assert both["AttributeDefinitions"] == [{"AttributeName": "pk", "AttributeType": "S"}, {"AttributeName": "ts", "AttributeType": "N"}]


def test_index_keys_are_declared_once_in_order() -> None:
    props = plain(keys("pk", "sk", gsis=[gsi("by-user", "user", "sk"), gsi("by-day", ("day", "N"))], lsis=[lsi("by-score", ("score", "N"))]))
    assert [a["AttributeName"] for a in props["AttributeDefinitions"]] == ["pk", "sk", "user", "day", "score"]
    assert props["GlobalSecondaryIndexes"][0] == {
        "IndexName": "by-user",
        "KeySchema": [{"AttributeName": "user", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}],
        "Projection": {"ProjectionType": "ALL"},
    }
    assert props["LocalSecondaryIndexes"][0]["KeySchema"] == [
        {"AttributeName": "pk", "KeyType": "HASH"},
        {"AttributeName": "score", "KeyType": "RANGE"},
    ]


def test_projections() -> None:
    props = plain(keys("pk", gsis=[gsi("a", "x", projection="KEYS_ONLY"), gsi("b", "y", projection=["name", "email"])]))
    assert [i["Projection"] for i in props["GlobalSecondaryIndexes"]] == [
        {"ProjectionType": "KEYS_ONLY"},
        {"ProjectionType": "INCLUDE", "NonKeyAttributes": ["name", "email"]},
    ]


def test_no_indexes_means_no_index_properties() -> None:
    assert set(keys("pk")) == {"AttributeDefinitions", "KeySchema"}


@pytest.mark.parametrize(
    ("build", "message"),
    [
        (lambda: keys("pk", gsis=[gsi("a", ("pk", "N"))]), "'pk' is declared as both S and N"),
        (lambda: keys("pk", gsis=[gsi("a", "x"), gsi("a", "y")]), "duplicate index names: a"),
        (lambda: keys("pk", gsis=[lsi("a", "x")]), "local index"),
        (lambda: keys("pk", lsis=[gsi("a", "x")]), "global index"),
    ],
)
def test_mistakes_are_refused(build, message: str) -> None:  # noqa: ANN001
    with pytest.raises(ValueError, match=message):
        build()


GOOD = """
from cfn_types import dynamodb

from cfn_typed.dynamodb import gsi, keys, lsi

dynamodb.table(**keys("pk"), BillingMode="PAY_PER_REQUEST")
dynamodb.table(**keys("pk", ("ts", "N"), gsis=[gsi("g", "user")], lsis=[lsi("l", "score")]), BillingMode="PAY_PER_REQUEST")
dynamodb.table(**keys("pk"), TimeToLiveSpecification={"Enabled": True, "AttributeName": "ttl"})
"""

BAD = {
    "an attribute type that does not exist": 'from cfn_typed.dynamodb import keys\nkeys("pk", ("ts", "X"))\n',
    "a projection that does not exist": 'from cfn_typed.dynamodb import gsi\ngsi("g", "pk", projection="SOME")\n',
    "a misspelled property next to the spread": 'from cfn_types import dynamodb\nfrom cfn_typed.dynamodb import keys\ndynamodb.table(**keys("pk"), BilingMode="x")\n',
    "a wrong type next to the spread": 'from cfn_types import dynamodb\nfrom cfn_typed.dynamodb import keys\ndynamodb.table(**keys("pk"), DeletionProtectionEnabled="yes")\n',
}


def check(tmp_path: Path, source: str) -> subprocess.CompletedProcess[str]:
    assert TY
    target = tmp_path / "snippet.py"
    target.write_text(source)
    return subprocess.run([TY, "check", "--output-format", "concise", str(target)], capture_output=True, text=True, cwd=ROOT)


@pytest.mark.skipif(TY is None, reason="needs the ty executable (run through `uv run`)")
def test_the_result_spreads_into_the_generated_table(tmp_path: Path) -> None:
    result = check(tmp_path, GOOD)
    assert result.returncode == 0, result.stdout


@pytest.mark.skipif(TY is None, reason="needs the ty executable (run through `uv run`)")
@pytest.mark.parametrize("name", sorted(BAD))
def test_mistakes_are_reported_before_running(tmp_path: Path, name: str) -> None:
    result = check(tmp_path, BAD[name])
    assert result.returncode != 0 and "error[" in result.stdout, f"{name} was not reported:\n{result.stdout}"
