"""The type promises of the policy statements, checked by running `ty` on code that breaks them."""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
TY = shutil.which("ty")

GOOD = """
from cfn_typed import AnyStatement, NotActionStatement, Statement, allow, deny

ok1: AnyStatement = {"Effect": "Allow", "Action": ["a:b"]}
ok2: AnyStatement = {"Effect": "Deny", "NotAction": ["iam:*"], "Resource": "*"}
ok3: list[AnyStatement] = [{"Effect": "Allow", "Action": "a:b"}, {"Effect": "Deny", "NotAction": "c:d", "NotResource": "arn"}]
c1 = Statement(Effect="Allow", Action=["a:b"])
c2 = NotActionStatement(Effect="Deny", NotAction=["a:b"])
b1 = allow(["a:b"], "arn")
b2 = deny(not_actions=["a:b"], resource="*")
"""

BAD = {
    "neither Action nor NotAction": 'from cfn_typed import AnyStatement\nx: AnyStatement = {"Effect": "Deny"}\n',
    "both Action and NotAction": 'from cfn_typed import AnyStatement\nx: AnyStatement = {"Effect": "Deny", "Action": ["a"], "NotAction": ["b"]}\n',
    "a misspelled key": 'from cfn_typed import AnyStatement\nx: AnyStatement = {"Efect": "Deny", "Action": ["a"]}\n',
    "a bad Effect": 'from cfn_typed import AnyStatement\nx: AnyStatement = {"Effect": "Alow", "Action": ["a"]}\n',
    "a constructor with a misspelled key": 'from cfn_typed import Statement\nStatement(Efect="Allow", Action=["a"])\n',
    "a constructor missing Action": 'from cfn_typed import Statement\nStatement(Effect="Allow")\n',
    "allow with neither form": 'from cfn_typed import allow\nallow()\n',
    "allow with both forms": 'from cfn_typed import allow\nallow(["a:b"], not_actions=["c:d"])\n',
}


def check(tmp_path: Path, source: str) -> subprocess.CompletedProcess[str]:
    assert TY
    target = tmp_path / "snippet.py"
    target.write_text(source)
    return subprocess.run([TY, "check", "--output-format", "concise", str(target)], capture_output=True, text=True, cwd=ROOT)


@pytest.mark.skipif(TY is None, reason="needs the ty executable (run through `uv run`)")
def test_valid_statements_pass(tmp_path: Path) -> None:
    result = check(tmp_path, GOOD)
    assert result.returncode == 0, result.stdout


@pytest.mark.skipif(TY is None, reason="needs the ty executable (run through `uv run`)")
@pytest.mark.parametrize("name", sorted(BAD))
def test_mistakes_are_reported_before_running(tmp_path: Path, name: str) -> None:
    result = check(tmp_path, BAD[name])
    assert result.returncode != 0 and "error[" in result.stdout, f"{name} was not reported:\n{result.stdout}"
