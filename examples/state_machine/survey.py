"""Look at a machine before porting it: what repeats, and where the quirks are. Usage: python survey.py machine.json"""

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


# --8<-- [start:survey]
def survey(definition: dict[str, Any]) -> list[str]:
    states: dict[str, Any] = definition["States"]
    lines = [f"{len(states)} states: {dict(Counter(s['Type'] for s in states.values()))}"]

    bodies = Counter(json.dumps({k: v for k, v in s.items() if k != "Next"}, sort_keys=True) for s in states.values() if s["Type"] == "Task")
    lines.append(f"{sum(bodies.values())} tasks, {len(bodies)} distinct bodies (ignoring Next): the fewer, the more a helper will save")

    catches = Counter(c["Next"] for s in states.values() for c in s.get("Catch", []))
    lines.append("where errors go: " + ", ".join(f"{target} x{n}" for target, n in catches.most_common()))

    loops = [name for name, s in states.items() if s["Type"] == "Wait" and states.get(s.get("Next"), {}).get("Type") == "Task"]
    lines.append(f"polling loops (a Wait that leads to a Task): {', '.join(loops) or 'none'}")

    no_handler = [n for n, s in states.items() if s["Type"] == "Task" and "Catch" not in s]
    lines.append(f"tasks with no Catch (handlers, or forgotten?): {', '.join(no_handler) or 'none'}")
    return lines
# --8<-- [end:survey]


if __name__ == "__main__":
    print("\n".join(survey(json.loads(Path(sys.argv[1]).read_text()))))
