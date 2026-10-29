"""The argument types of the intrinsic builders, checked by running `ty` on code that gets them wrong."""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
TY = shutil.which("ty")

GOOD = """
import cfn_typed as cfn
from cfn_typed import and_, condition_ref, equals, get_att, get_azs, if_, join, not_, ref, select, split, sub

a = join("/", ["", "orders", ref("Stage")])
b = join(",", split(",", "x,y"))              # parts may be an intrinsic that returns a list
c = select(0, get_azs())
d = sub("${A}", {"A": ref("P"), "B": "literal"})
e = get_att("Q", ref("Which"))
f = if_("C", 1, ref("AWS::NoValue"))
t: cfn.Template = {"Conditions": {"X": and_(equals(ref("S"), "p"), not_(condition_ref("Y")))}, "Resources": {}}
"""

BAD = {
    "join parts that are not a list": 'from cfn_typed import join\\njoin("/", "abc")\\n',
    "sub variables that are not strings": 'from cfn_typed import sub\\nsub("${A}", {"A": 1})\\n',
    "get_att with a number as the attribute": 'from cfn_typed import get_att\\nget_att("Q", 3)\\n',
    "equals missing an argument": 'from cfn_typed import equals\\nequals("a")\\n',
    "a value instead of a condition function in Conditions": 'import cfn_typed as cfn\\nt: cfn.Template = {"Conditions": {"X": "yes"}, "Resources": {}}\\n',
    "split with a list as the source": 'from cfn_typed import split\\nsplit(",", ["a"])\\n',
    "and_ given a non-condition": 'from cfn_typed import and_\\nand_("a", "b")\\n',
}


def check(tmp_path: Path, source: str) -> subprocess.CompletedProcess[str]:
    assert TY
    target = tmp_path / "snippet.py"
    target.write_text(source)
    return subprocess.run([TY, "check", "--output-format", "concise", str(target)], capture_output=True, text=True, cwd=ROOT)


@pytest.mark.skipif(TY is None, reason="needs the ty executable (run through `uv run`)")
def test_valid_uses_pass(tmp_path: Path) -> None:
    result = check(tmp_path, GOOD)
    assert result.returncode == 0, result.stdout


@pytest.mark.skipif(TY is None, reason="needs the ty executable (run through `uv run`)")
@pytest.mark.parametrize("name", sorted(BAD))
def test_mistakes_are_reported_before_running(tmp_path: Path, name: str) -> None:
    result = check(tmp_path, BAD[name])
    assert result.returncode != 0 and "error[" in result.stdout, f"{name} was not reported:\n{result.stdout}"
