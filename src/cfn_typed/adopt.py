"""Bring resources that already exist outside the stack under its management (CloudFormation resource import).

Some tools make resources with API calls, not in the template: the Serverless Framework's `serverless-domain-manager` plugin
creates the API's custom domain and its mapping that way. Ejecting such a service means putting those resources in the
template, and CloudFormation cannot create a domain that exists. It can import it:

    ids = {"CustomDomain": {"DomainName": "api.example.com"}, "Mapping": {"DomainName": "api.example.com", "BasePath": "(none)"}}
    resources = resources_to_import(template, ids, load_schemas(CACHE))     # checked against the registry schemas
    plan("ledger-dev", template, resources_to_import=resources, keep=True, change_set_name="adopt")

The identifier of a resource is its type's `primaryIdentifier` in the registry schema, and `find_adopt_problems` says which
keys a type needs. An import change set may only import: the same template, with the resources added, and nothing else
changed. So adopting is its own deploy, before the one that changes the template. What CloudFormation requires:

- every imported resource has a `DeletionPolicy` in the template (use `Retain`, so that a later removal cannot delete it);
- its properties in the template describe what exists (a difference is drift, found by the next update, not by the import);
- the type supports import, which is a list kept by AWS (docs: "Resource type support" for resource import).
"""

from collections.abc import Mapping, Sequence
from typing import Any

type Schemas = Sequence[Mapping[str, Any]]


def primary_identifier(type_name: str, schemas: Schemas) -> list[str] | None:
    """The property names that identify a resource of `type_name` (`["DomainName", "BasePath"]`), or None for a type the schemas do not have."""
    for schema in schemas:
        if schema.get("typeName") == type_name:
            return [path.rsplit("/", 1)[-1] for path in schema.get("primaryIdentifier", [])]
    return None


def find_adopt_problems(template: Mapping[str, Any], identifiers: Mapping[str, Mapping[str, str]], schemas: Schemas) -> list[str]:
    """What stops these resources being imported, one readable line each: a logical ID that is not in the template, a type the schemas do not know, identifier keys that are not the type's primary identifier, no `DeletionPolicy`."""
    out: list[str] = []
    resources = template.get("Resources") or {}
    for logical, ident in identifiers.items():
        resource = resources.get(logical)
        if not isinstance(resource, Mapping):
            out.append(f"{logical}: not a resource in the template")
            continue
        type_name = str(resource.get("Type"))
        keys = primary_identifier(type_name, schemas)
        if keys is None:
            out.append(f"{logical}: no registry schema for {type_name}")
        elif set(keys) != set(ident):
            out.append(f"{logical} ({type_name}): the identifier is {', '.join(keys) or 'unknown'}, not {', '.join(ident) or 'nothing'}")
        if "DeletionPolicy" not in resource:
            out.append(f"{logical}: an imported resource needs a DeletionPolicy (Retain)")
    return out


def resources_to_import(template: Mapping[str, Any], identifiers: Mapping[str, Mapping[str, str]], schemas: Schemas) -> list[dict[str, Any]]:
    """The `ResourcesToImport` list for `aws cloudformation create-change-set --change-set-type IMPORT`. Raises `ValueError` with every problem `find_adopt_problems` finds."""
    problems = find_adopt_problems(template, identifiers, schemas)
    if problems:
        raise ValueError("cannot import:\n" + "\n".join(f"  {p}" for p in problems))
    return [
        {"ResourceType": template["Resources"][logical]["Type"], "LogicalResourceId": logical, "ResourceIdentifier": dict(ident)}
        for logical, ident in identifiers.items()
    ]


__all__: Sequence[str] = ["find_adopt_problems", "primary_identifier", "resources_to_import"]
