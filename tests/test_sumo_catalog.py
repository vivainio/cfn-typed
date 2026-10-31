"""docs/sumo-patterns.md links every pattern to its code by line number; fail when the code moves and the page does not."""

import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
PAGE = ROOT / "docs" / "sumo-patterns.md"
SRC = ROOT / "packages" / "sumo" / "src" / "cfn_typed_sumo"
LINK = re.compile(r"\[`(\w+)`\]\(https://github\.com/vivainio/cfn-typed/blob/main/packages/sumo/src/cfn_typed_sumo/(\w+)\.py#L(\d+)\)")


def test_every_link_points_at_the_definition() -> None:
    links = LINK.findall(PAGE.read_text())
    assert len(links) > 40
    for name, module, line in links:
        text = (SRC / f"{module}.py").read_text().split("\n")[int(line) - 1]
        assert re.match(rf"(def|class) {name}\b|{name}\b *[:=]", text), f"{name}: {module}.py line {line} is {text!r}; regenerate the page"


def test_book_links_exist() -> None:
    for page in re.findall(r"\]\((patterns/[\w-]+\.md)\)", PAGE.read_text()):
        assert (ROOT / "docs" / page).is_file(), page
