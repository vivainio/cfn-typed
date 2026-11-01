"""Where a Lambda function's code is: S3, a local file for `aws cloudformation package`, or inline.

The result is typed `Any` on purpose. Resource types are generated per project, and each has its own `FunctionCode`,
so no type here could be the right one. The arguments are checked; the result fits wherever a function's `Code` goes.
"""

import ast
from os import PathLike, fspath
from pathlib import Path
from typing import Any

from cfn_typed.intrinsics import Expr

INLINE_LIMIT = 4096


def s3(bucket: Expr[str], key: Expr[str], *, version: Expr[str] | None = None) -> Any:
    """A zip that is already in S3, uploaded by your build. CloudFormation reads it itself, so nothing is downloaded.

    The bucket must be in the stack's region, and whoever deploys needs `s3:GetObject` on the object. Lambda only updates
    when these properties change, so use a key that is new for each build (a git SHA, a build number, a content hash), or a
    versioned bucket and `version`.
    """
    code: dict[str, Expr[str]] = {"S3Bucket": bucket, "S3Key": key}
    if version is not None:
        code["S3ObjectVersion"] = version
    return code


def local(path: str | PathLike[str]) -> Any:
    """A local zip file or directory, for `aws cloudformation package` to upload and rewrite before `deploy`.

    The template holds the path as a plain string, which is what `package` looks for, so the rendered file is not
    deployable until it has been packaged. A relative path is relative to the template file.
    """
    return fspath(path)


def inline(source: str) -> Any:
    """The source itself, in the template (`ZipFile`). Python and Node.js only, up to 4096 characters, no dependencies.

    CloudFormation writes it to `index.py` (or `index.js`), so the function's handler must be `index.handler`.
    """
    if len(source) > INLINE_LIMIT:
        raise ValueError(f"inline code is {len(source)} characters; CloudFormation allows {INLINE_LIMIT}")
    return {"ZipFile": source}


def inline_file(path: str | PathLike[str]) -> Any:
    """`inline`, with the source read from a file when the template is rendered.

    The source stays a real file you can lint and test, and the template stays self-contained: no upload, no `package`.
    A `.py` file is parsed, so a syntax error fails at render time and not when the function is first called. It is
    one file, written as `index.py` by CloudFormation, so the handler is `index.handler` and it cannot import your other
    modules. Anchor a relative path with `Path(__file__).parent`, or it depends on where `emit` runs.
    """
    file = Path(path)
    source = file.read_text(encoding="utf-8")
    if file.suffix == ".py":
        ast.parse(source, filename=str(file))
    return inline(source)
