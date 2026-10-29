"""cfn_typed — CloudFormation as typed Python dicts.

Resource factories live in generated modules (`cfn_typed.aws.sqs`, ...); this
package holds the intrinsics, template types and a few helpers.
"""

from cfn_typed.base import AnyResource, Output, Resources, Tag, Template
from cfn_typed.helpers import DDB_WRITE, SQS_CONSUME, Statement, allow, merge, tags
from cfn_typed.intrinsics import Expr, Intrinsic, arn, get_att, import_value, join, ref, sub

__all__ = [
    "AnyResource", "DDB_WRITE", "Expr", "Intrinsic", "Output", "Resources", "SQS_CONSUME", "Statement", "Tag", "Template",
    "allow", "arn", "get_att", "import_value", "join", "merge", "ref", "sub", "tags",
]
