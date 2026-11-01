from cfn_typed_sumo.constructs import function

from cfn_typed import code
from cfn_typed.testing import assert_template_ok


def test_every_code_location_goes_into_function() -> None:
    for c, handler in ((code.s3("artifacts", "w/abc.zip"), "app.handler"), (code.inline("def handler(e, c): pass"), "index.handler")):
        f = function("Worker", code=c, handler=handler, runtime="python3.13")
        assert f.resources["Worker"]["Properties"]["Code"] == c
        assert_template_ok({"Resources": f.resources})


def test_local_path_is_what_function_renders() -> None:
    f = function("Worker", code=code.local("dist/worker.zip"), handler="app.handler", runtime="python3.13")
    assert f.resources["Worker"]["Properties"]["Code"] == "dist/worker.zip"
