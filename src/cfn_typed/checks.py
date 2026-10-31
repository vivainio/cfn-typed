"""Run every check on a finished template in one call.

    problems = find_all_problems(template, cfn_types)   # {} when nothing is wrong

The result maps the name of each check that found something to its problems, one readable line each:

- `references`: dangling names, unguarded references to conditional resources, dependency cycles (`cfn_typed.references`);
- `unused`: parameters, conditions and mappings nothing refers to (`unused=False` leaves it out);
- `limits`: CloudFormation quotas and naming rules (`cfn_typed.limits`);
- `values`: `Fn::FindInMap` keys, `Fn::Select` indexes and parameter defaults (`cfn_typed.values`);
- `iam`: unknown actions, resources of the wrong service, S3 bucket-versus-object ARNs (`cfn_typed.iam`);
- `asl`: the state graph of each state machine whose definition is written out in the template (`cfn_typed.asl`);
- `lifecycle`: Lambda runtimes past their deprecation date (`cfn_typed.lifecycle`; `today` is for tests);
- any `rules` the company passes (`cfn_typed.query` helps to write them), each under its function name;
- `constraints`, `attributes` and `combinations`: values, `Fn::GetAtt` names and "one of / needs" property combinations
  against the registry schemas (`cfn_typed.constraints`, `cfn_typed.attributes`, `cfn_typed.combinations`). They need `types`, the package `cfn-typegen` generated (a hand-made mapping means something different to each, so
  use the two functions directly for that), and are left out without it.
"""

from collections.abc import Callable, Mapping, Sequence
from datetime import date
from types import ModuleType
from typing import Any

from cfn_typed.asl import find_state_machine_problems
from cfn_typed.attributes import find_attribute_problems
from cfn_typed.combinations import find_combination_problems
from cfn_typed.constraints import find_constraint_problems
from cfn_typed.iam import find_iam_problems
from cfn_typed.lifecycle import find_lifecycle_problems
from cfn_typed.limits import find_limit_problems
from cfn_typed.references import find_reference_problems, find_unused_problems
from cfn_typed.values import find_value_problems

type Rule = Callable[[Mapping[str, Any]], list[str]]
"""A company's own check: the template in, one readable line per problem out."""


def find_all_problems(
    template: Mapping[str, Any],
    types: ModuleType | None = None,
    *,
    inline: bool = False,
    unused: bool = True,
    defaults: bool = True,
    today: date | None = None,
    rules: Sequence[Rule] = (),
) -> dict[str, list[str]]:
    """Every problem any check finds in `template`, grouped by check. `inline`, `unused`, `defaults` and `today` are passed to the checks they name. Each of `rules` is a check of the company's own and reports under its function name."""
    found = {
        "references": find_reference_problems(template),
        "unused": find_unused_problems(template) if unused else [],
        "limits": find_limit_problems(template, inline=inline),
        "values": find_value_problems(template, defaults=defaults),
        "iam": find_iam_problems(template),
        "asl": find_state_machine_problems(template),
        "lifecycle": find_lifecycle_problems(template, today=today, defaults=defaults),
        "constraints": find_constraint_problems(template, types, defaults=defaults) if types is not None else [],
        "attributes": find_attribute_problems(template, types) if types is not None else [],
        "combinations": find_combination_problems(template, types) if types is not None else [],
    }
    for rule in rules:
        found[getattr(rule, "__name__", repr(rule))] = rule(template)
    return {check: problems for check, problems in found.items() if problems}
