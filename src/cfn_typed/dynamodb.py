"""DynamoDB key plumbing: `AttributeDefinitions`, `KeySchema` and the indexes, derived from the keys alone.

Optional: `dynamodb.table(...)` takes these properties directly, and nothing else in the library needs this module.

CloudFormation wants every key attribute of the table and of every index declared once in `AttributeDefinitions`.
Writing that list by hand is where the mistakes are, so `keys` collects it. The result is a fragment of
`TableProps` that you spread into the generated factory:

    dynamodb.table(**keys("pk", ("ts", "N"), gsis=[gsi("by-user", "user")]), BillingMode="PAY_PER_REQUEST")

The result is a plain dict, so this module needs no generated types. The arguments carry the precise types (an
attribute type is `"S"`, `"N"` or `"B"`), and `tests/test_dynamodb.py` checks the output against the key shapes.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

AttrType = Literal["S", "N", "B"]
ProjectionType = Literal["ALL", "KEYS_ONLY"]

# A key is its attribute name, which is a string, or `(name, type)`.
Key = str | tuple[str, AttrType]


@dataclass(frozen=True)
class Index:
    """A secondary index, made by `gsi` or `lsi` and turned into properties by `keys`."""

    name: str
    hash: tuple[str, AttrType] | None  # None for a local index: it uses the table's hash key
    range: tuple[str, AttrType] | None
    projection: dict[str, Any]


def _key(key: Key) -> tuple[str, AttrType]:
    return (key, "S") if isinstance(key, str) else key


def _projection(projection: ProjectionType | list[str]) -> dict[str, Any]:
    if isinstance(projection, str):
        return {"ProjectionType": projection}
    return {"ProjectionType": "INCLUDE", "NonKeyAttributes": list(projection)}


def gsi(name: str, pk: Key, sk: Key | None = None, *, projection: ProjectionType | list[str] = "ALL") -> Index:
    """A global secondary index. `projection` is `"ALL"`, `"KEYS_ONLY"` or the attribute names to include."""
    return Index(name, _key(pk), _key(sk) if sk is not None else None, _projection(projection))


def lsi(name: str, sk: Key, *, projection: ProjectionType | list[str] = "ALL") -> Index:
    """A local secondary index: the table's hash key and its own range key."""
    return Index(name, None, _key(sk), _projection(projection))


def _schema(hash_key: tuple[str, AttrType], range_key: tuple[str, AttrType] | None) -> list[dict[str, str]]:
    schema: list[dict[str, str]] = [{"AttributeName": hash_key[0], "KeyType": "HASH"}]
    if range_key:
        schema.append({"AttributeName": range_key[0], "KeyType": "RANGE"})
    return schema


def keys(
    pk: Key,
    sk: Key | None = None,
    *,
    gsis: Sequence[Index] = (),
    lsis: Sequence[Index] = (),
) -> dict[str, Any]:
    """The key properties of a table: `AttributeDefinitions`, `KeySchema` and any indexes.

    Each attribute is declared once, in the order it first appears. Using one name with two types raises
    `ValueError`, and so does a name used for two indexes, or `gsi` where `lsi` belongs.
    """
    table_hash = _key(pk)
    table_range = _key(sk) if sk is not None else None
    attributes: dict[str, AttrType] = {}

    def declare(attr: tuple[str, AttrType]) -> None:
        name, type_ = attr
        if attributes.setdefault(name, type_) != type_:
            raise ValueError(f"attribute {name!r} is declared as both {attributes[name]} and {type_}")

    declare(table_hash)
    if table_range:
        declare(table_range)

    names = [i.name for i in (*gsis, *lsis)]
    if len(set(names)) != len(names):
        raise ValueError(f"duplicate index names: {', '.join(sorted({n for n in names if names.count(n) > 1}))}")

    global_indexes: list[dict[str, Any]] = []
    for index in gsis:
        if index.hash is None:
            raise ValueError(f"index {index.name!r} is a local index: pass it as `lsis`")
        declare(index.hash)
        if index.range:
            declare(index.range)
        global_indexes.append({"IndexName": index.name, "KeySchema": _schema(index.hash, index.range), "Projection": index.projection})

    local_indexes: list[dict[str, Any]] = []
    for index in lsis:
        if index.hash is not None:
            raise ValueError(f"index {index.name!r} is a global index: pass it as `gsis`")
        if index.range:
            declare(index.range)
        local_indexes.append({"IndexName": index.name, "KeySchema": _schema(table_hash, index.range), "Projection": index.projection})

    out: dict[str, Any] = {
        "AttributeDefinitions": [{"AttributeName": n, "AttributeType": t} for n, t in attributes.items()],
        "KeySchema": _schema(table_hash, table_range),
    }
    if global_indexes:
        out["GlobalSecondaryIndexes"] = global_indexes
    if local_indexes:
        out["LocalSecondaryIndexes"] = local_indexes
    return out
