"""Template parameters as variables: declare once, use the returned `Ref` anywhere.

    params = Params()
    vpc_id = params.ssm("VpcId", "/platform/network/vpc-id")   # a plain Ref
    ...
    template["Parameters"] = params.declarations()

SSM parameters are template parameters of an SSM type, so CloudFormation looks the value
up at deploy time and shows it in change sets. Nothing is read when the template is built.
"""

import re

from cfn_typed.base import Parameter
from cfn_typed.intrinsics import Ref, ref

_LOGICAL_ID = re.compile(r"[A-Za-z0-9]+")


class Params:
    """A registry of template parameters. Each declaration returns the `Ref` to use."""

    def __init__(self) -> None:
        self._declared: dict[str, Parameter] = {}

    def _declare(self, name: str, decl: Parameter) -> Ref:
        if not _LOGICAL_ID.fullmatch(name):
            raise ValueError(f"parameter names are letters and digits only, got {name!r}")
        existing = self._declared.get(name)
        if existing is not None and existing != decl:
            raise ValueError(f"parameter {name!r} is already declared differently")
        self._declared[name] = decl  # declaring the same thing twice is fine and returns the same Ref
        return ref(name)

    def string(
        self,
        name: str,
        *,
        default: str | None = None,
        description: str | None = None,
        allowed_values: list[str] | None = None,
        no_echo: bool = False,
    ) -> Ref:
        decl: Parameter = {"Type": "String"}
        if default is not None:
            decl["Default"] = default
        if description:
            decl["Description"] = description
        if allowed_values:
            decl["AllowedValues"] = allowed_values
        if no_echo:
            decl["NoEcho"] = True
        return self._declare(name, decl)

    def number(self, name: str, *, default: int | float | None = None, description: str | None = None) -> Ref:
        decl: Parameter = {"Type": "Number"}
        if default is not None:
            decl["Default"] = default
        if description:
            decl["Description"] = description
        return self._declare(name, decl)

    def ssm(self, name: str, path: str, *, description: str | None = None) -> Ref:
        """A String (or String-typed SecureString-free) SSM parameter, resolved by CloudFormation at deploy time."""
        return self._declare(name, self._ssm_decl("AWS::SSM::Parameter::Value<String>", path, description))

    def ssm_list(self, name: str, path: str, *, description: str | None = None) -> Ref:
        """An SSM StringList parameter. The `Ref` is accepted wherever a list of strings is."""
        return self._declare(name, self._ssm_decl("AWS::SSM::Parameter::Value<List<String>>", path, description))

    @staticmethod
    def _ssm_decl(type_name: str, path: str, description: str | None) -> Parameter:
        if not path:
            raise ValueError("an SSM parameter needs a path")
        decl: Parameter = {"Type": type_name, "Default": path}  # the Default is the parameter's *name* in SSM
        if description:
            decl["Description"] = description
        return decl

    def declarations(self) -> dict[str, Parameter]:
        """The `Parameters` section for the template (a copy)."""
        return dict(self._declared)


def dynamic_ssm(path: str, *, secure: bool = False, version: int | None = None) -> str:
    """A `{{resolve:ssm:...}}` dynamic reference, as a plain string.

    Unlike `Params.ssm`, this needs no template parameter, but CloudFormation only accepts it in
    some properties, and `secure=True` (SecureString) in even fewer. Check the resource's
    documentation before using it for secrets.
    """
    kind = "ssm-secure" if secure else "ssm"
    suffix = f":{version}" if version is not None else ""
    return "{{resolve:" + kind + ":" + path + suffix + "}}"
