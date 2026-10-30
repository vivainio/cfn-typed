"""Check a finished template for Lambda runtimes AWS has deprecated or no longer lets you use.

    problems = find_lifecycle_problems(template)   # [] when no function uses a runtime past its deprecation date

Every `AWS::Lambda::Function` `Runtime` is read through the intrinsics the template decides (a parameter's allowed values or
default, `Fn::If`, `Fn::FindInMap`). A runtime is reported once it is deprecated, and says whether creating or updating a
function with it is already blocked. A date in the future is not reported. The dates are in `cfn_typed._lambda_runtimes`,
copied from cfn-lint; `scripts/sync-lambda-runtimes.py` refreshes them, and they go stale like any data.
"""

from collections.abc import Mapping
from datetime import date
from typing import Any

from cfn_typed._lambda_runtimes import RUNTIMES
from cfn_typed.constraints import _Resolver


def _due(when: str | None, today: date) -> bool:
    return when is not None and date.fromisoformat(when) <= today


def find_lifecycle_problems(template: Mapping[str, Any], *, today: date | None = None, defaults: bool = True) -> list[str]:
    """Every Lambda function whose runtime is past its deprecation date, one readable line each. `today` is for tests."""
    today = today or date.today()
    resolver = _Resolver(template, defaults)
    out: list[str] = []
    for logical, resource in template.get("Resources", {}).items():
        props = resource.get("Properties")
        if resource.get("Type") != "AWS::Lambda::Function" or not isinstance(props, Mapping) or "Runtime" not in props:
            continue
        for runtime, origin in resolver.candidates(props["Runtime"]):
            entry = RUNTIMES.get(runtime) if isinstance(runtime, str) else None
            if entry is None or not _due(entry[0], today):
                continue
            deprecated, create, update, successor = entry
            where = f"Resources.{logical}.Properties.Runtime"
            note = f" ({origin})" if origin else ""
            use = f"; use {successor}" if successor else ""
            if _due(create, today):
                out.append(f"{where}: {runtime!r} was deprecated {deprecated} and functions can no longer be created with it (since {create}){use}{note}")
            elif _due(update, today):
                out.append(f"{where}: {runtime!r} was deprecated {deprecated} and functions can no longer be updated with it (since {update}){use}{note}")
            else:
                blocks = ", ".join(f"{what} blocked from {when}" for what, when in (("creating", create), ("updating", update)) if when)
                out.append(f"{where}: {runtime!r} is deprecated since {deprecated}{f' ({blocks})' if blocks else ''}{use}{note}")
    return list(dict.fromkeys(out))
