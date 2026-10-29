"""The repo ships no generated types; generate the ones the examples use before tests import them."""

from pathlib import Path

from cfn_typed import typegen

OUT = Path(__file__).parent.parent / "examples" / "cfn_types"
TYPES = ["AWS::SQS::Queue", "AWS::Lambda::Function", "AWS::Lambda::EventSourceMapping", "AWS::IAM::Role"]

if not OUT.exists():
    typegen.main(["--out", str(OUT), *TYPES])
