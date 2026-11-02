"""Check the code a template points at: the zip, and the S3 objects the functions read.

An empty change set proves the template did not change. It proves nothing about a file inside a zip, and nothing about an
object in a bucket, so a function that lost a file on the way (a wrapper the framework used to add at deploy time) deploys
fine and fails when it is first called. These checks cover that:

    find_zip_problems("build/app.zip", required=["app.py"], handler="app.handler")   # [] when the zip is sound
    find_wsgi_problems("build/app.zip", app="api.app")                                # the Serverless WSGI plugin's three files
    call_handler("build/app.zip", "app.handler", {"path": "/health"})                 # run the handler once, in a subprocess
    find_missing_code(template, buckets={"ServerlessDeploymentBucket": "my-bucket"})  # every S3Key the template names exists

The zip checks read the file only. `call_handler` runs the code in the zip, in a fresh interpreter, so run it on a zip you
built and trust. `find_missing_code` calls `aws s3api head-object`, once for each distinct object.
"""

import ast
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from collections.abc import Callable, Mapping, Sequence
from os import PathLike
from typing import Any

WSGI_FILES = ("wsgi_handler.py", "serverless_wsgi.py", ".serverless-wsgi")
"""What the `serverless-wsgi` plugin puts in the package. `wsgi_handler.py` exists only in the plugin's npm package, not on
PyPI; `serverless_wsgi.py` is the PyPI package `serverless-wsgi`; `.serverless-wsgi` is written from `custom.wsgi.app`."""

WSGI_HANDLER = "wsgi_handler.handler"
"""The Lambda `Handler` of a function the plugin packaged. It is not `serverless_wsgi.handler`."""


def wsgi_config(app: str, *, text_mime_types: Sequence[str] | None = None) -> str:
    """The text of `.serverless-wsgi`: JSON with the WSGI application as `module.variable` (`custom.wsgi.app`) and, when set, `text_mime_types`.

    Compare it with the file in a package from a real `sls package` before relying on it: the plugin owns the format.
    """
    config: dict[str, Any] = {"app": app}
    if text_mime_types:
        config["text_mime_types"] = list(text_mime_types)
    return json.dumps(config)


def _members(path: str | PathLike[str]) -> dict[str, zipfile.ZipInfo]:
    with zipfile.ZipFile(path) as archive:
        return {info.filename: info for info in archive.infolist() if not info.is_dir()}


def _module_files(module: str) -> tuple[str, str]:
    base = module.replace(".", "/")
    return f"{base}.py", f"{base}/__init__.py"


def find_zip_problems(path: str | PathLike[str], required: Sequence[str] = (), *, handler: str | None = None) -> list[str]:
    """What is wrong with the zip at `path`, one readable line each; `[]` when it is sound.

    `required` are member names that must be in it. `handler` is a Python Lambda `Handler` (`pkg.module.function`): its module
    must be in the zip, parse, and define the function. A file that is not a zip, or is not there, is a problem too.
    """
    try:
        members = _members(path)
    except (OSError, zipfile.BadZipFile) as err:
        return [f"{path}: cannot read the zip ({err})"]
    out = [f"{path}: missing {name}" for name in required if name not in members]
    if handler is not None:
        module, _, function = handler.rpartition(".")
        if not module:
            return [*out, f"{path}: handler {handler!r} is not module.function"]
        found = next((name for name in _module_files(module) if name in members), None)
        if found is None:
            out.append(f"{path}: handler {handler!r}: no {_module_files(module)[0]} in the zip")
        else:
            with zipfile.ZipFile(path) as archive:
                try:
                    tree = ast.parse(archive.read(found), filename=found)
                except SyntaxError as err:
                    out.append(f"{path}: {found} does not parse ({err.msg}, line {err.lineno})")
                else:
                    names = {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
                    names |= {t.id for n in tree.body if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name)}
                    names |= {a.asname or a.name.split(".")[0] for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom)) for a in n.names}
                    if function not in names and not any(isinstance(n, ast.ImportFrom) and any(a.name == "*" for a in n.names) for n in tree.body):
                        out.append(f"{path}: {found} does not define {function!r}")
    return out


def find_wsgi_problems(path: str | PathLike[str], *, app: str | None = None) -> list[str]:
    """`find_zip_problems` for a function the Serverless WSGI plugin packaged: the three `WSGI_FILES`, `wsgi_handler.handler`, and a `.serverless-wsgi` whose `app` is a module in the zip (and is `app`, when given)."""
    out = find_zip_problems(path, WSGI_FILES, handler=WSGI_HANDLER)
    try:
        members = _members(path)
        if ".serverless-wsgi" not in members:
            return out
        with zipfile.ZipFile(path) as archive:
            config = json.loads(archive.read(".serverless-wsgi"))
    except (OSError, zipfile.BadZipFile):
        return out
    except ValueError as err:
        return [*out, f"{path}: .serverless-wsgi is not JSON ({err})"]
    target = config.get("app") if isinstance(config, dict) else None
    if not isinstance(target, str) or "." not in target:
        return [*out, f"{path}: .serverless-wsgi has no 'app' of the form module.variable"]
    if app is not None and target != app:
        out.append(f"{path}: .serverless-wsgi says app {target!r}, expected {app!r}")
    module = target.rpartition(".")[0]
    if not any(name in members for name in _module_files(module)):
        out.append(f"{path}: .serverless-wsgi app {target!r}: no {_module_files(module)[0]} in the zip")
    return out


_RUNNER = """
import importlib, json, sys
root, handler = sys.argv[1], sys.argv[2]
sys.path.insert(0, root)
module, _, name = handler.rpartition(".")
event = json.load(sys.stdin)
class Context:
    function_name = "local"; function_version = "$LATEST"; memory_limit_in_mb = 128; aws_request_id = "local"
    invoked_function_arn = "arn:aws:lambda:local:000000000000:function:local"
    def get_remaining_time_in_millis(self): return 30000
result = getattr(importlib.import_module(module), name)(event, Context())
sys.stdout.write("\\n" + json.dumps(result, default=str))
"""


def call_handler(
    path: str | PathLike[str], handler: str, event: Mapping[str, Any], *, env: Mapping[str, str] | None = None, timeout: float = 60,
) -> Any:
    """Unpack the zip, import `handler` (`module.function`) in a fresh Python and call it once with `event`; return its JSON result.

    A stand-in context is passed. The code in the zip runs with this interpreter and the zip's own files first on `sys.path`, so
    what it imports from the zip is what was packaged; anything else it needs must be installed here. `env` is added to the
    environment. Raises `AssertionError` with the traceback when the call fails. Run it only on a zip you built.
    """
    with tempfile.TemporaryDirectory() as root:
        with zipfile.ZipFile(path) as archive:
            archive.extractall(root)
        done = subprocess.run(
            [sys.executable, "-c", _RUNNER, root, handler],
            input=json.dumps(event), capture_output=True, text=True, timeout=timeout, cwd=root, env={**os.environ, **(env or {})},
        )
    if done.returncode != 0:
        raise AssertionError(f"{handler} failed when called with the event:\n{done.stderr.strip()}")
    return json.loads(done.stdout.rpartition("\n")[2])


type Exists = Callable[[str, str], bool]
"""Does the S3 object exist: `(bucket, key) -> bool`."""


def s3_object_exists(bucket: str, key: str, *, profile: str | None = None, region: str | None = None) -> bool:
    """Whether `aws s3api head-object` finds the object. Any failure, such as a missing permission, counts as not found."""
    command = ["aws", "s3api", "head-object", "--bucket", bucket, "--key", key]
    if profile:
        command += ["--profile", profile]
    if region:
        command += ["--region", region]
    return subprocess.run(command, capture_output=True).returncode == 0


def _code_locations(template: Mapping[str, Any]) -> list[tuple[str, str, Any, Any]]:
    """(logical id, where, bucket, key) of every S3 location a function, layer or SAM function names."""
    found: list[tuple[str, str, Any, Any]] = []
    for logical, resource in (template.get("Resources") or {}).items():
        props = resource.get("Properties") if isinstance(resource, Mapping) else None
        if not isinstance(props, Mapping):
            continue
        match resource.get("Type"):
            case "AWS::Lambda::Function":
                code, where = props.get("Code"), "Code"
            case "AWS::Lambda::LayerVersion":
                code, where = props.get("Content"), "Content"
            case _:
                continue
        if isinstance(code, Mapping) and "S3Key" in code:
            found.append((logical, where, code.get("S3Bucket"), code["S3Key"]))
    return found


def find_missing_code(
    template: Mapping[str, Any], exists: Exists | None = None, *, buckets: Mapping[str, str] | None = None,
) -> list[str]:
    """The functions and layers whose S3 code object is not there, one readable line each.

    A bucket that is a literal name is used as it is. A `Ref` to a bucket in the template needs its real name in `buckets`
    (`{"ServerlessDeploymentBucket": "svc-dev-serverlessdeploymentbucket-abc"}`); one that cannot be resolved is reported
    and not guessed. `exists` is `s3_object_exists` unless you pass your own. Each object is looked up once.
    """
    check = exists or s3_object_exists
    seen: dict[tuple[str, str], bool] = {}
    out: list[str] = []
    for logical, where, bucket, key in _code_locations(template):
        if isinstance(bucket, Mapping) and set(bucket) == {"Ref"}:
            bucket = (buckets or {}).get(bucket["Ref"])
            if bucket is None:
                out.append(f"Resources.{logical}.Properties.{where}: the bucket is a Ref that was not given a name (pass buckets=)")
                continue
        if not isinstance(bucket, str) or not isinstance(key, str):
            out.append(f"Resources.{logical}.Properties.{where}: bucket or key is not a literal, so it was not checked")
            continue
        if (bucket, key) not in seen:
            seen[bucket, key] = check(bucket, key)
        if not seen[bucket, key]:
            out.append(f"Resources.{logical}.Properties.{where}: s3://{bucket}/{key} does not exist")
    return out


__all__: Sequence[str] = [
    "WSGI_FILES", "WSGI_HANDLER", "call_handler", "find_missing_code", "find_wsgi_problems", "find_zip_problems", "s3_object_exists", "wsgi_config",
]
