"""Run every check on a finished template in one call.

    problems = find_all_problems(template, cfn_types)   # {} when nothing is wrong

The result maps the name of each check that found something to its problems, one readable line each:

- `references`: dangling names, unguarded references to conditional resources, dependency cycles (`cfn_typed.references`);
- `unused`: parameters, conditions and mappings nothing refers to (`unused=False` leaves it out);
- `limits`: CloudFormation quotas and naming rules (`cfn_typed.limits`);
- `constraints` and `attributes`: values and `Fn::GetAtt` names against the registry schemas (`cfn_typed.constraints`,
  `cfn_typed.attributes`). They need `types`, the package `cfn-typegen` generated (a hand-made mapping means something different to each, so
  use the two functions directly for that), and are left out without it.
"""

from collections.abc import Mapping
from types import ModuleType
from typing import Any

from cfn_typed.attributes import find_attribute_problems
from cfn_typed.constraints import find_constraint_problems
from cfn_typed.limits import find_limit_problems
from cfn_typed.references import find_reference_problems, find_unused_problems


def find_all_problems(
    template: Mapping[str, Any],
    types: ModuleType | None = None,
    *,
    inline: bool = False,
    unused: bool = True,
    defaults: bool = True,
) -> dict[str, list[str]]:
    """Every problem any check finds in `template`, grouped by check. `inline`, `unused` and `defaults` are passed to the checks they name."""
    found = {
        "references": find_reference_problems(template),
        "unused": find_unused_problems(template) if unused else [],
        "limits": find_limit_problems(template, inline=inline),
        "constraints": find_constraint_problems(template, types, defaults=defaults) if types is not None else [],
        "attributes": find_attribute_problems(template, types) if types is not None else [],
    }
    return {check: problems for check, problems in found.items() if problems}
