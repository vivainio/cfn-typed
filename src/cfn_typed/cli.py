"""An optional command line for your stack script: `emit`, `check`, `diff` and `ls`.

    # stacks.py
    import cfn_typed as cfn
    from cfn_typed import cli

    def orders() -> cfn.Template: ...

    def run() -> int:
        return cli.main({"orders-prod": orders, "orders-dev": partial(orders, "dev")}, schemas=cfn_types)

    if __name__ == "__main__":
        sys.exit(run())

    $ python stacks.py emit orders-prod -f yaml     # print one stack
    $ python stacks.py emit -o rendered/            # write every stack to rendered/<name>.yaml
    $ python stacks.py check                        # every check; exit status 1 when anything is found
    $ python stacks.py ls --type 'AWS::SQS::*'  # logical id, type and name of each resource
    $ python stacks.py diff rendered/               # compare with the committed files; --update rewrites them

It also works with no Python code at all: give it template files (JSON, or YAML with short-form intrinsics) and use `cfn-typed`
(or `python -m cfn_typed.cli`):

    $ cfn-typed check template.yaml other.json
    $ cfn-typed ls template.yaml -t lambda
    $ cfn-typed emit template.yaml -f json          # convert between JSON and YAML
    $ cfn-typed check template.yaml --schemas cfn_types   # add the schema checks from a generated package

Nothing else in `cfn_typed` imports this module, and it needs nothing beyond the standard library (`-f yaml` needs `cfn-typed[yaml]`).
`stacks` is one builder (a function that returns the template) or a mapping from stack name to builder.
"""

import argparse
import difflib
import fnmatch
import importlib
import json
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from types import ModuleType
from typing import Any

from cfn_typed.checks import Rule, find_all_problems
from cfn_typed.testing import render_for

type Builder = Callable[[], Mapping[str, Any]]

_FORMATS = {"json": ".json", "yaml": ".yaml"}


def _short_form(loader: Any, suffix: str, node: Any) -> dict[str, Any]:
    """Inverse of the YAML short forms: `!Ref X` is `{"Ref": "X"}`, `!GetAtt A.Arn` is `{"Fn::GetAtt": ["A", "Arn"]}`."""
    from yaml import MappingNode, ScalarNode, SequenceNode

    if isinstance(node, ScalarNode):
        value: Any = loader.construct_scalar(node)
    elif isinstance(node, SequenceNode):
        value = loader.construct_sequence(node, deep=True)
    elif isinstance(node, MappingNode):
        value = loader.construct_mapping(node, deep=True)
    else:
        raise TypeError(node)
    if suffix == "GetAtt" and isinstance(value, str):
        value = value.split(".", 1)
    return {suffix if suffix in ("Ref", "Condition") else f"Fn::{suffix}": value}


def load_template(path: Path) -> dict[str, Any]:
    """Read a template file: JSON, or YAML (needs PyYAML) with the short-form intrinsics (`!Ref`, `!GetAtt A.Arn`, `!Sub`, ...)."""
    text = path.read_text()
    if path.suffix == ".json" or text.lstrip().startswith("{"):
        return json.loads(text)
    try:
        import yaml
    except ImportError:
        raise SystemExit(f"{path}: reading YAML needs PyYAML (pip install cfn-typed[yaml])") from None

    class Loader(yaml.SafeLoader):
        pass

    Loader.add_multi_constructor("!", _short_form)
    return yaml.load(text, Loader=Loader)  # noqa: S506 (a SafeLoader subclass)


def skill_dir() -> Path:
    """The agent skill's directory: `cfn_typed/skill` in an installed package, `skills/cfn-typed` in a source checkout."""
    from importlib.resources import files

    packaged = Path(str(files("cfn_typed") / "skill"))
    return packaged if (packaged / "SKILL.md").is_file() else Path(__file__).resolve().parents[2] / "skills" / "cfn-typed"


def skill_text() -> str:
    """SKILL.md with a line after the frontmatter that says where the skill's directory is, so its relative links (`resources/...`) can be followed."""
    text = (skill_dir() / "SKILL.md").read_text(encoding="utf-8")
    end = text.find("\n---\n", 3)
    note = f"\n> Skill directory: `{skill_dir()}`. Files linked as `resources/...` below are in it.\n"
    return text if end < 0 else text[: end + 5] + note + text[end + 5 :]


def _from_files(paths: Sequence[str], ap: argparse.ArgumentParser) -> dict[str, Builder]:
    if not paths:
        ap.error("give at least one template file")
    named: dict[str, Builder] = {}
    for text in paths:
        path = Path(text)
        if not path.is_file():
            ap.error(f"no such file: {path}")
        if path.stem in named:
            ap.error(f"two templates are called {path.stem!r}")
        named[path.stem] = lambda path=path: load_template(path)
    return named


def _select(stacks: Mapping[str, Builder], names: Sequence[str], ap: argparse.ArgumentParser) -> dict[str, Builder]:
    unknown = [n for n in names if n not in stacks]
    if unknown:
        ap.error(f"unknown stack {', '.join(unknown)} (known: {', '.join(stacks)})")
    return {n: stacks[n] for n in names} if names else dict(stacks)


def _emit(args: argparse.Namespace, chosen: Mapping[str, Builder]) -> int:
    out: Path | None = args.out
    fmt = args.format or (out.suffix.lstrip(".").replace("yml", "yaml") if out and out.suffix else "yaml")
    if fmt not in _FORMATS:
        print(f"unknown format {fmt!r}, use json or yaml", file=sys.stderr)
        return 2
    if out is None:
        if len(chosen) > 1:
            print(f"name a stack to print ({', '.join(chosen)}) or use -o DIR to write all of them", file=sys.stderr)
            return 2
        (build,) = chosen.values()
        sys.stdout.write(render_for(Path(f"x{_FORMATS[fmt]}"), build()))
        return 0
    if len(chosen) == 1 and out.suffix:
        targets = {out: next(iter(chosen.values()))}
    else:
        targets = {out / f"{name}{_FORMATS[fmt]}": build for name, build in chosen.items()}
    for path, build in targets.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_for(path, build()))
        print(f"wrote {path}", file=sys.stderr)
    return 0


def _check(args: argparse.Namespace, chosen: Mapping[str, Builder], schemas: ModuleType | None, rules: Sequence[Rule]) -> int:
    failed = 0
    for name, build in chosen.items():
        problems = find_all_problems(
            build(), schemas, inline=args.inline, unused=not args.no_unused, defaults=not args.no_defaults, rules=rules,
        )
        if not problems:
            print(f"{name}: ok")
            continue
        failed += 1
        print(f"{name}: {sum(map(len, problems.values()))} problem(s)")
        for check, lines in problems.items():
            for line in lines:
                print(f"  [{check}] {line}")
    return 1 if failed else 0


_NAME_PROPERTY = {
    "AWS::ApiGateway::RestApi": "Name",
    "AWS::ApiGatewayV2::Api": "Name",
    "AWS::AppSync::GraphQLApi": "Name",
    "AWS::Athena::WorkGroup": "Name",
    "AWS::Cognito::UserPoolClient": "ClientName",
    "AWS::EC2::SecurityGroup": "GroupName",
    "AWS::EKS::Cluster": "Name",
    "AWS::ElasticLoadBalancingV2::LoadBalancer": "Name",
    "AWS::ElasticLoadBalancingV2::TargetGroup": "Name",
    "AWS::Events::EventBus": "Name",
    "AWS::Events::Rule": "Name",
    "AWS::Kinesis::Stream": "Name",
    "AWS::Lambda::LayerVersion": "LayerName",
    "AWS::RDS::DBInstance": "DBInstanceIdentifier",
    "AWS::Route53::HostedZone": "Name",
    "AWS::SecretsManager::Secret": "Name",
    "AWS::SSM::Parameter": "Name",
}
"""The resources whose name property is not `<Kind>Name`. Add to it when a type shows a blank name."""


_ALIASES = {
    "api": "AWS::ApiGatewayV2::Api",
    "bucket": "AWS::S3::Bucket",
    "cluster": "AWS::ECS::Cluster",
    "db": "AWS::RDS::DBInstance",
    "distribution": "AWS::CloudFront::Distribution",
    "lambda": "AWS::Lambda::Function",
    "lb": "AWS::ElasticLoadBalancingV2::LoadBalancer",
    "log": "AWS::Logs::LogGroup",
    "policy": "AWS::IAM::*Policy",
    "queue": "AWS::SQS::Queue",
    "role": "AWS::IAM::Role",
    "rule": "AWS::Events::Rule",
    "secret": "AWS::SecretsManager::Secret",
    "sg": "AWS::EC2::SecurityGroup",
    "table": "AWS::DynamoDB::Table",
    "topic": "AWS::SNS::Topic",
}
"""Short names for `ls`: `-t` accepts them, and the listing shows them (`-l` for the full type names). Types without an alias lose only the `AWS::IAM::` prefix. A word that is neither an alias nor a glob with `::` matches the last part of a type name, so `-t function` finds every `...::Function`."""


_SHORT = {type_name: alias for alias, type_name in _ALIASES.items() if "*" not in type_name}


def _short_type(type_name: str) -> str:
    """The alias when there is one; else the type without its `AWS::IAM::` prefix (`ManagedPolicy`); else the full name."""
    return _SHORT.get(type_name) or type_name.removeprefix("AWS::IAM::")


def _type_pattern(text: str) -> str:
    key = text.lower()
    if key in _ALIASES:
        return _ALIASES[key]
    return text if "::" in text or "*" in text else f"*::{text}"


def _name_of(type_name: str, props: Mapping[str, Any]) -> str:
    """The resource's own name when it is a literal: from `_NAME_PROPERTY`, else `QueueName` for `AWS::SQS::Queue`, `FunctionName` for `AWS::Lambda::Function`."""
    value = props.get(_NAME_PROPERTY.get(type_name, type_name.rsplit("::", 1)[-1] + "Name"))
    return value if isinstance(value, str) else ""


def _resources(args: argparse.Namespace, chosen: Mapping[str, Builder]) -> int:
    pattern = _type_pattern(args.type or "*").lower()
    for name, build in chosen.items():
        rows = [
            (logical, res.get("Type", "") if args.long else _short_type(res.get("Type", "")), _name_of(res.get("Type", ""), res.get("Properties") or {}))
            for logical, res in (build().get("Resources") or {}).items()
            if fnmatch.fnmatchcase(res.get("Type", "").lower(), pattern)
        ]
        print(f"{name}: {len(rows)} resource(s)")
        widths = [max((len(r[i]) for r in rows), default=0) for i in range(2)]
        for logical, type_name, own in rows:
            print(f"  {logical:<{widths[0]}}  {type_name:<{widths[1]}}  {own}".rstrip())
    return 0


def _diff(args: argparse.Namespace, chosen: Mapping[str, Builder]) -> int:
    ext = _FORMATS[args.format]
    failed = 0
    for name, build in chosen.items():
        path = args.dir / f"{name}{ext}"
        actual = render_for(path, build())
        expected = path.read_text() if path.exists() else None
        if expected == actual:
            print(f"{name}: matches {path}")
        elif args.update:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(actual)
            print(f"{name}: wrote {path}")
        else:
            failed += 1
            if expected is None:
                print(f"{name}: {path} does not exist (create it with --update)")
            else:
                print("".join(difflib.unified_diff(expected.splitlines(True), actual.splitlines(True), str(path), "rendered")), end="")
    return 1 if failed else 0


def main(
    stacks: Builder | Mapping[str, Builder] | None = None,
    *,
    schemas: ModuleType | None = None,
    rules: Sequence[Rule] = (),
    argv: Sequence[str] | None = None,
    prog: str | None = None,
) -> int:
    """Run the command line for `stacks` and return the exit status (0 ok, 1 problems or differences, 2 bad usage; `--help` and argument errors still exit by themselves, as argparse does). `schemas` is the package `cfn-typegen` generated: it enables the checks against the registry schemas (values, `GetAtt` names, property combinations), which are left out without it. `rules` are the company's own checks. Both are for `check` (see `find_all_problems`). Without `stacks` the arguments are template files (the `cfn-typed` command)."""
    standalone = stacks is None
    named: Mapping[str, Builder] = {} if stacks is None else stacks if isinstance(stacks, Mapping) else {"template": stacks}

    ap = argparse.ArgumentParser(prog=prog, description="Render and check CloudFormation templates.")
    sub = ap.add_subparsers(dest="command", required=True)
    stack_help = "template files" if standalone else f"stack names (default: all of {', '.join(named)})"

    p = sub.add_parser("emit", help="print a template, or write the templates to files")
    p.add_argument("stack", nargs="*", help=stack_help)
    p.add_argument("-f", "--format", choices=list(_FORMATS), help="default: from the -o suffix, else yaml")
    p.add_argument("-o", "--out", type=Path, help="a file (one stack) or a directory (writes NAME.yaml for each)")

    p = sub.add_parser("check", help="run every check; exit status 1 when one finds a problem")
    p.add_argument("stack", nargs="*", help=stack_help)
    p.add_argument("--inline", action="store_true", help="templates are sent inline, so the 51,200-byte limit applies")
    p.add_argument("--no-unused", action="store_true", help="skip the unused parameter/condition/mapping check")
    p.add_argument("--no-defaults", action="store_true", help="do not check parameter defaults")
    if standalone:
        p.add_argument("--schemas", metavar="MODULE", help="a package generated by cfn-typegen, to check against the registry schemas")

    p = sub.add_parser("ls", help="list the resources: logical id, type and name")
    p.add_argument("stack", nargs="*", help=stack_help)
    p.add_argument("-l", "--long", action="store_true", help="show full type names, not aliases")
    p.add_argument("-t", "--type", help="only these types: an alias (queue, lambda, role, ...), a glob such as 'AWS::SQS::*', or the last part of a type name")

    p = sub.add_parser("diff", help="compare the rendered templates with the committed files")
    p.add_argument("dir", type=Path, help="directory that holds NAME.yaml for each stack")
    p.add_argument("stack", nargs="*", help=stack_help)
    p.add_argument("-f", "--format", choices=list(_FORMATS), default="yaml")
    p.add_argument("--update", action="store_true", help="rewrite the files instead of failing")

    if standalone:
        p = sub.add_parser("import", help="write a template file as typed Python (types from `cfn-typegen --template FILE`)")
        p.add_argument("template", type=Path)
        p.add_argument("-o", "--out", type=Path, help="write the module to this file instead of printing it")
        p.add_argument("--types", default="cfn_types", help="the package cfn-typegen generated (default: cfn_types)")

        p = sub.add_parser("skill", help="print the agent skill (SKILL.md) that teaches an AI assistant to use cfn-typed, and where its directory is")
        p.add_argument("--dir", action="store_true", help="print only the skill's directory (it holds SKILL.md and resources/)")

    args = ap.parse_args(argv)
    if args.command == "skill":
        print(skill_dir() if args.dir else skill_text(), end="\n" if args.dir else "")
        return 0
    if args.command == "import":
        from cfn_typed import importer

        if not args.template.is_file():
            ap.error(f"no such file: {args.template}")
        return importer.main(str(args.template), str(args.out) if args.out else None, args.types)
    if standalone:
        chosen = _from_files(args.stack, ap)
        if getattr(args, "schemas", None):
            sys.path.insert(0, ".")
            schemas = importlib.import_module(args.schemas)
    else:
        chosen = _select(named, args.stack, ap)
    match args.command:
        case "emit":
            return _emit(args, chosen)
        case "check":
            return _check(args, chosen, schemas, rules)
        case "ls":
            return _resources(args, chosen)
        case _:
            return _diff(args, chosen)


def run() -> None:
    """The `cfn-typed` command: the same subcommands on template files."""
    sys.exit(main(prog="cfn-typed"))


if __name__ == "__main__":
    run()
