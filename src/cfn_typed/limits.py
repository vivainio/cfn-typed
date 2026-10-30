"""Check a finished template against CloudFormation's documented quotas and naming rules.

    problems = find_limit_problems(template)   # [] when the template is within every limit

Checked: at most 500 resources, 200 parameters, 200 outputs and 200 mappings, each mapping with at most 200 top-level
keys; logical IDs are letters and digits only; the description is at most 1,024 bytes; the template is at most
1,000,000 bytes of JSON (the S3 limit, or 51,200 with `inline=True` for a body sent directly).
CloudFormation reports these only at deploy time. Quotas change, so the numbers are in `LIMITS`.
"""

import json
import re
from collections.abc import Mapping
from typing import Any

LIMITS = {"Resources": 500, "Parameters": 200, "Outputs": 200, "Mappings": 200}
MAPPING_ATTRIBUTES = 200
DESCRIPTION_BYTES = 1024
TEMPLATE_BYTES = 1_000_000
INLINE_TEMPLATE_BYTES = 51_200
_LOGICAL_ID = re.compile(r"^[A-Za-z0-9]+$")
_NAMED = ("Resources", "Parameters", "Outputs", "Conditions", "Mappings")


def find_limit_problems(template: Mapping[str, Any], *, inline: bool = False) -> list[str]:
    """Every quota or naming rule `template` breaks, one readable line each. `inline` applies the smaller limit for a template body sent directly."""
    problems: list[str] = []
    for section, most in LIMITS.items():
        count = len(template.get(section, {}))
        if count > most:
            problems.append(f"{section}: {count} entries, but a template may have at most {most}")
    for name, body in template.get("Mappings", {}).items():
        if isinstance(body, Mapping) and len(body) > MAPPING_ATTRIBUTES:
            problems.append(f"Mappings.{name}: {len(body)} top-level keys, but a mapping may have at most {MAPPING_ATTRIBUTES}")
    for section in _NAMED:
        for name in template.get(section, {}):
            if not _LOGICAL_ID.match(name):
                problems.append(f"{section}.{name}: a logical ID may only have letters and digits")
    description = template.get("Description")
    if isinstance(description, str) and len(description.encode()) > DESCRIPTION_BYTES:
        problems.append(f"Description: {len(description.encode())} bytes, but at most {DESCRIPTION_BYTES} are allowed")
    size = len(json.dumps(template, separators=(",", ":")).encode())
    most = INLINE_TEMPLATE_BYTES if inline else TEMPLATE_BYTES
    if size > most:
        problems.append(f"Template: {size} bytes as compact JSON, but at most {most} are allowed")
    return problems
