"""An optional command line for your stack script: `emit`, `check`, `diff` and `ls`.

    # stacks.py
    import cfn_typed as cfn
    from cfn_typed import cli

    def orders() -> cfn.Template: ...

    def run() -> int:
        return cli.main({"orders": orders, "billing": billing}, schemas=cfn_types)

    if __name__ == "__main__":
        sys.exit(run())

    $ python stacks.py emit orders -f yaml     # print one stack
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

Nothing else in `cfn_typed` imports this module, and it needs nothing beyond the standard library and PyYAML.
`stacks` is one builder (a function that returns the template) or a mapping from stack name to builder. A value can also be a
`StackSpec(build, out=DIR)`, so that `emit` and `diff` know where that stack's template is rendered.
`settings=Settings` (a dataclass) turns its fields into flags, and each builder that takes an argument gets an instance; see `main`.
"""

import argparse
import dataclasses
import difflib
import enum
import fnmatch
import functools
import importlib
import inspect
import json
import os
import sys
import types
import typing
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

from cfn_typed.checks import Rule, find_all_problems
from cfn_typed.testing import render_for

type Builder = Callable[..., Mapping[str, Any]]  # no argument, or one settings instance


@dataclass(frozen=True)
class StackSpec:
    """A builder and, optionally, the directory its template is rendered into.

    Use it as a value in the mapping given to `main`, wherever a plain builder would go. With `out` set, `emit` and `diff`
    write and compare `<out>/<name>.yaml` without being told a directory; `-o DIR` (or the directory argument of `diff`)
    still overrides it for every stack. `out` is used as given, so relative paths are relative to the current directory:
    build it from `Path(__file__)` to make it independent of where the script is run.

    `settings` is a dataclass for this stack, in place of the one given to `main`: its fields are command line flags, and
    `build` is called with an instance. See `main`.
    """

    build: Builder
    out: Path | str | None = None
    settings: type | None = None

    @property
    def out_dir(self) -> Path | None:
        return None if self.out is None else Path(self.out)

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
    import yaml

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


def _from_files(paths: Sequence[str], ap: argparse.ArgumentParser) -> dict[str, StackSpec]:
    if not paths:
        ap.error("give at least one template file")
    named: dict[str, StackSpec] = {}
    for text in paths:
        path = Path(text)
        if not path.is_file():
            ap.error(f"no such file: {path}")
        if path.stem in named:
            ap.error(f"two templates are called {path.stem!r}")
        named[path.stem] = StackSpec(lambda path=path: load_template(path))
    return named


def _specs(stacks: Builder | StackSpec | Mapping[str, Builder | StackSpec]) -> dict[str, StackSpec]:
    def one(value: Builder | StackSpec) -> StackSpec:
        return value if isinstance(value, StackSpec) else StackSpec(value)

    if isinstance(stacks, Mapping):
        return {name: one(value) for name, value in stacks.items()}
    return {"template": one(stacks)}


def _select(stacks: Mapping[str, StackSpec], names: Sequence[str], ap: argparse.ArgumentParser) -> dict[str, StackSpec]:
    unknown = [n for n in names if n not in stacks]
    if unknown:
        ap.error(f"unknown stack {', '.join(unknown)} (known: {', '.join(stacks)})")
    return {n: stacks[n] for n in names} if names else dict(stacks)


def _emit(args: argparse.Namespace, chosen: Mapping[str, StackSpec]) -> int:
    out: Path | None = args.out
    to_stdout = out == Path("-")
    fmt = args.format or (out.suffix.lstrip(".").replace("yml", "yaml") if out and out.suffix else "yaml")
    if fmt not in _FORMATS:
        print(f"unknown format {fmt!r}, use json or yaml", file=sys.stderr)
        return 2
    if to_stdout or (out is None and not any(spec.out for spec in chosen.values()) and len(chosen) == 1):
        if len(chosen) > 1:
            print(f"name a stack to print ({', '.join(chosen)})", file=sys.stderr)
            return 2
        (spec,) = chosen.values()
        sys.stdout.write(render_for(Path(f"x{_FORMATS[fmt]}"), spec.build()))
        return 0
    if out is None:
        missing = [name for name, spec in chosen.items() if spec.out is None]
        if missing:
            print(f"no output directory for {', '.join(missing)}: use -o DIR, or give the stack a StackSpec with out=", file=sys.stderr)
            return 2
        targets = {Path(spec.out) / f"{name}{_FORMATS[fmt]}": spec.build for name, spec in chosen.items() if spec.out is not None}
    elif len(chosen) == 1 and out.suffix:
        targets = {out: next(iter(chosen.values())).build}
    else:
        targets = {out / f"{name}{_FORMATS[fmt]}": spec.build for name, spec in chosen.items()}
    for path, build in targets.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_for(path, build()))
        print(f"wrote {path}", file=sys.stderr)
    return 0


def _check(args: argparse.Namespace, chosen: Mapping[str, StackSpec], schemas: ModuleType | None, rules: Sequence[Rule]) -> int:
    failed = 0
    for name, spec in chosen.items():
        problems = find_all_problems(
            spec.build(), schemas, inline=args.inline, unused=not args.no_unused, defaults=not args.no_defaults, rules=rules,
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


def _resources(args: argparse.Namespace, chosen: Mapping[str, StackSpec]) -> int:
    pattern = _type_pattern(args.type or "*").lower()
    for name, spec in chosen.items():
        rows = [
            (logical, res.get("Type", "") if args.long else _short_type(res.get("Type", "")), _name_of(res.get("Type", ""), res.get("Properties") or {}))
            for logical, res in (spec.build().get("Resources") or {}).items()
            if fnmatch.fnmatchcase(res.get("Type", "").lower(), pattern)
        ]
        print(f"{name}: {len(rows)} resource(s)" + (f" -> {spec.out}" if spec.out is not None else ""))
        widths = [max((len(r[i]) for r in rows), default=0) for i in range(2)]
        for logical, type_name, own in rows:
            print(f"  {logical:<{widths[0]}}  {type_name:<{widths[1]}}  {own}".rstrip())
    return 0


def _diff(args: argparse.Namespace, chosen: Mapping[str, StackSpec]) -> int:
    ext = _FORMATS[args.format]
    failed = 0
    for name, spec in chosen.items():
        directory = args.dir if args.dir is not None else spec.out_dir
        if directory is None:
            print(f"{name}: no directory: give one, or give the stack a StackSpec with out=", file=sys.stderr)
            return 2
        path = directory / f"{name}{ext}"
        actual = render_for(path, spec.build())
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


@dataclass(frozen=True)
class _Kind:
    convert: Callable[[str], Any]
    boolean: bool = False
    many: bool = False


def _to_bool(text: str) -> bool:
    if text.lower() in ("true", "1", "yes"):
        return True
    if text.lower() in ("false", "0", "no"):
        return False
    raise argparse.ArgumentTypeError(f"{text!r} is not true or false")


def _kind(tp: Any, name: str) -> _Kind:
    origin = typing.get_origin(tp)
    if origin is types.UnionType or origin is typing.Union:
        args = [a for a in typing.get_args(tp) if a is not type(None)]
        if len(args) == 1:
            return _kind(args[0], name)
    elif origin is typing.Literal:
        choices = {str(v): v for v in typing.get_args(tp)}

        def pick(text: str) -> Any:
            if text not in choices:
                raise argparse.ArgumentTypeError(f"{text!r} is not one of {', '.join(choices)}")
            return choices[text]

        return _Kind(pick)
    elif origin is list:
        (item,) = typing.get_args(tp) or (str,)
        return _Kind(_kind(item, name).convert, many=True)
    elif tp is bool:
        return _Kind(_to_bool, boolean=True)
    elif tp in (str, int, float):
        return _Kind(tp)
    elif tp is Path:
        return _Kind(Path)
    elif isinstance(tp, type) and issubclass(tp, enum.Enum):
        def member(text: str) -> Any:
            if text not in tp.__members__:
                raise argparse.ArgumentTypeError(f"{text!r} is not one of {', '.join(tp.__members__)}")
            return tp[text]

        return _Kind(member)
    raise TypeError(f"settings field {name!r}: {tp!r} cannot be a command line flag (use str, int, float, bool, Path, an Enum, a Literal, a list of those, or X | None)")


@dataclass(frozen=True)
class _Setting:
    name: str
    tp: Any
    kind: _Kind
    default: Any
    required: bool
    env: str | None
    help: str

    @property
    def flag(self) -> str:
        return "--" + self.name.replace("_", "-")

    @property
    def dest(self) -> str:
        return f"settings__{self.name}"  # never the same as a built-in option's name


def _settings_of(cls: type) -> dict[str, _Setting]:
    if not (isinstance(cls, type) and dataclasses.is_dataclass(cls)):
        raise TypeError(f"settings must be a dataclass, not {cls!r}")
    hints = typing.get_type_hints(cls)
    out: dict[str, _Setting] = {}
    for f in dataclasses.fields(cls):
        if not f.init:
            continue
        required = f.default is dataclasses.MISSING and f.default_factory is dataclasses.MISSING
        factory = f.default_factory
        default = None if required else (f.default if factory is dataclasses.MISSING else factory())
        out[f.name] = _Setting(f.name, hints[f.name], _kind(hints[f.name], f.name), default, required, f.metadata.get("env"), f.metadata.get("help", ""))
    return out


def _all_settings(specs: Mapping[str, StackSpec], shared: type | None) -> dict[str, _Setting]:
    """The flags of every settings class in use. A name that two classes declare has to have the same type; whether it has a default is up to each class, and is checked when that class's stack is built."""
    merged: dict[str, _Setting] = {}
    owner: dict[str, type] = {}
    for cls in {c for spec in specs.values() if (c := spec.settings or shared) is not None}:
        for name, setting in _settings_of(cls).items():
            if name in merged and merged[name].tp != setting.tp:
                raise TypeError(f"settings field {name!r} has a different type in {owner[name].__name__} and {cls.__name__}")
            merged.setdefault(name, setting)
            owner.setdefault(name, cls)
    return merged


def _add_flags(p: argparse.ArgumentParser, settings: Mapping[str, _Setting]) -> None:
    for s in settings.values():
        note = "required" if s.required else f"default: {s.default}"
        text = " ".join(part for part in (s.help, f"({note}{', or $' + s.env if s.env else ''})") if part)
        try:
            if s.kind.boolean:
                p.add_argument(s.flag, dest=s.dest, action=argparse.BooleanOptionalAction, default=argparse.SUPPRESS, help=text)
            else:
                p.add_argument(s.flag, dest=s.dest, type=s.kind.convert, action="append" if s.kind.many else "store", default=argparse.SUPPRESS, metavar=s.name.upper(), help=text)
        except argparse.ArgumentError:
            raise TypeError(f"settings field {s.name!r}: {s.flag} is already an option of the {p.prog.split()[-1]} command, rename the field") from None


def _instance(cls: type, args: argparse.Namespace, ap: argparse.ArgumentParser, stack: str) -> Any:
    values: dict[str, Any] = {}
    missing: list[str] = []
    for s in _settings_of(cls).values():
        if hasattr(args, s.dest):
            values[s.name] = getattr(args, s.dest)
        elif s.env and s.env in os.environ:
            try:
                values[s.name] = [s.kind.convert(v) for v in os.environ[s.env].split(",")] if s.kind.many else s.kind.convert(os.environ[s.env])
            except (ValueError, argparse.ArgumentTypeError) as e:
                ap.error(f"${s.env}: {e}")
        elif s.required:
            missing.append(s.flag + (f" (or ${s.env})" if s.env else ""))
    if missing:
        ap.error(f"{stack}: the following arguments are required: {', '.join(missing)}")
    try:
        return cls(**values)
    except ValueError as e:
        ap.error(f"{stack}: {e}")


def _takes_argument(build: Callable[..., Any]) -> bool:
    try:
        params = inspect.signature(build).parameters.values()
    except (TypeError, ValueError):
        return False
    return any(p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD, p.VAR_POSITIONAL) for p in params)


def _with_settings(chosen: Mapping[str, StackSpec], shared: type | None, args: argparse.Namespace, ap: argparse.ArgumentParser) -> dict[str, StackSpec]:
    """Each stack's builder with its settings instance filled in. A builder that takes no argument is left alone when it only has the shared settings."""
    out: dict[str, StackSpec] = {}
    for name, spec in chosen.items():
        cls = spec.settings or (shared if _takes_argument(spec.build) else None)
        if cls is None:
            out[name] = spec
        else:
            out[name] = dataclasses.replace(spec, build=functools.partial(spec.build, _instance(cls, args, ap, name)))
    return out


def main(
    stacks: Builder | StackSpec | Mapping[str, Builder | StackSpec] | None = None,
    *,
    schemas: ModuleType | None = None,
    rules: Sequence[Rule] = (),
    settings: type | None = None,
    argv: Sequence[str] | None = None,
    prog: str | None = None,
) -> int:
    """Run the command line for `stacks` and return the exit status (0 ok, 1 problems or differences, 2 bad usage; `--help` and argument errors still exit by themselves, as argparse does). `schemas` is the package `cfn-typegen` generated: it enables the checks against the registry schemas (values, `GetAtt` names, property combinations), which are left out without it. `rules` are the company's own checks. Both are for `check` (see `find_all_problems`). `settings` is a dataclass whose fields become flags on `emit`, `check`, `diff` and `ls` (`--stage prod`): each builder that takes an argument is called with an instance, and a field with no default is required. A `StackSpec(build, settings=Other)` uses `Other` for that stack instead; a flag is only required by the stacks you select. Without `stacks` the arguments are template files (the `cfn-typed` command)."""
    standalone = stacks is None
    if standalone and settings is not None:
        raise TypeError("settings go with stacks: template files take no settings")
    named: Mapping[str, StackSpec] = {} if stacks is None else _specs(stacks)
    flags = _all_settings(named, settings)

    ap = argparse.ArgumentParser(prog=prog, description="Render and check CloudFormation templates.")
    sub = ap.add_subparsers(dest="command", required=True)
    stack_help = "template files" if standalone else f"stack names (default: all of {', '.join(named)})"

    p = sub.add_parser("emit", help="print a template, or write the templates to files")
    p.add_argument("stack", nargs="*", help=stack_help)
    p.add_argument("-f", "--format", choices=list(_FORMATS), help="default: from the -o suffix, else yaml")
    p.add_argument("-o", "--out", type=Path, help="a file (one stack), a directory (writes NAME.yaml for each; overrides a StackSpec's out) or - for standard output")
    _add_flags(p, flags)

    p = sub.add_parser("check", help="run every check; exit status 1 when one finds a problem")
    p.add_argument("stack", nargs="*", help=stack_help)
    p.add_argument("--inline", action="store_true", help="templates are sent inline, so the 51,200-byte limit applies")
    p.add_argument("--no-unused", action="store_true", help="skip the unused parameter/condition/mapping check")
    p.add_argument("--no-defaults", action="store_true", help="do not check parameter defaults")
    _add_flags(p, flags)
    if standalone:
        p.add_argument("--schemas", metavar="MODULE", help="a package generated by cfn-typegen, to check against the registry schemas")

    p = sub.add_parser("ls", help="list the resources: logical id, type and name")
    p.add_argument("stack", nargs="*", help=stack_help)
    p.add_argument("-l", "--long", action="store_true", help="show full type names, not aliases")
    p.add_argument("-t", "--type", help="only these types: an alias (queue, lambda, role, ...), a glob such as 'AWS::SQS::*', or the last part of a type name")
    _add_flags(p, flags)

    p = sub.add_parser("diff", help="compare the rendered templates with the committed files")
    p.add_argument("args", nargs="*", metavar="[DIR] [STACK]", help="directory that holds NAME.yaml for each stack (omit it to use each StackSpec's out), then stack names; if the first word is a stack name, there is no directory")
    p.add_argument("-f", "--format", choices=list(_FORMATS), default="yaml")
    p.add_argument("--update", action="store_true", help="rewrite the files instead of failing")
    _add_flags(p, flags)

    if standalone:
        p = sub.add_parser("import", help="write a template file as typed Python (types from `cfn-typegen --template FILE`)")
        p.add_argument("template", type=Path)
        p.add_argument("-o", "--out", type=Path, help="write the module to this file instead of printing it")
        p.add_argument("--types", default="cfn_types", help="the package cfn-typegen generated (default: cfn_types)")
        p.add_argument("--asl", action="store_true", help="write each state machine's DefinitionString (Step Functions ASL) as a Definition object, typed and checked by cfn_typed.asl; the module then no longer renders to exactly the original")

        p = sub.add_parser("skill", help="print the agent skill (SKILL.md) that teaches an AI assistant to use cfn-typed, and where its directory is")
        p.add_argument("--dir", action="store_true", help="print only the skill's directory (it holds SKILL.md and resources/)")

    args = ap.parse_args(argv)
    if args.command == "diff":
        first, *rest = args.args or [None]
        args.dir, args.stack = (None, args.args) if first is None or first in named else (Path(first), rest)
        if args.dir is None and standalone:
            ap.error("give a directory")
    if args.command == "skill":
        print(skill_dir() if args.dir else skill_text(), end="\n" if args.dir else "")
        return 0
    if args.command == "import":
        from cfn_typed import importer

        if not args.template.is_file():
            ap.error(f"no such file: {args.template}")
        return importer.main(str(args.template), str(args.out) if args.out else None, args.types, args.asl)
    if standalone:
        chosen = _from_files(args.stack, ap)
        if getattr(args, "schemas", None):
            sys.path.insert(0, ".")
            schemas = importlib.import_module(args.schemas)
    else:
        chosen = _with_settings(_select(named, args.stack, ap), settings, args, ap)
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
