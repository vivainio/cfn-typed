# Ejecting from the Serverless Framework

!!! note "Two kinds of ejecting"
    This page is about leaving the Serverless Framework (or SAM) for a service that is already deployed. Moving
    patterns you used from `cfn-typed-sumo` into your own package is a different thing, described in
    [cfn-typed-sumo](../sumo.md#recommended-start-with-sumo-then-eject-what-you-use). The two meet at the end of this page, in
    [dropping the sumo dependency](#dropping-the-sumo-dependency).

!!! tip "Start here"
    Install both packages: `uv add cfn-typed cfn-typed-sumo`. `cfn-typed-sumo` has the Serverless helpers (`cfn_typed_sumo.sls`, and
    `cfn-typed import --sls`, which writes calls to them) and the generated types for about 440 resource types, so you can
    pass `--types cfn_typed_sumo.types` to `import` and skip `cfn-typegen` for ordinary stacks. The checks (`check --live`,
    `zip`) are in `cfn-typed` itself. When the ejected services are running smoothly, you can
    [drop the sumo dependency](#dropping-the-sumo-dependency) by copying the helpers into your own package.

The [Serverless Framework in a few lines](../patterns/serverless.md) page shows what a `functions:` entry becomes as patterns. This page
is for a service that already runs: you want to stop using the framework for it, and you do not want CloudFormation to
replace anything when you do.

The framework is a template generator, and `sls package` writes what it generates. So ejecting is not a rewrite
from the YAML. It is taking that template, turning it into Python that renders to exactly the same template, and then
changing it from there. The example is made up: a `ledger` service with one scheduled Python function, in
[`examples/serverless_eject`](https://github.com/vivainio/cfn-typed/tree/main/examples/serverless_eject). Its
`original.json` is written the way `sls package` writes one, with the framework's names, but it did not come from a real run
and nothing in it is from a real account.

## Where it goes

A Serverless service is one repository, and it keeps its infrastructure in a `cfn/` directory next to `serverless.yml`, in the
layout of [a typical project](../project-layout.md). The ejection adds to it as you go:

```text
my-service/                         # the repository that had serverless.yml
  serverless.yml                    # stays until the ejected stack has deployed with an empty change set; then delete it
  src/                              # the application, and the build step that makes the zip (it stays outside cfn/)
  cfn/
    cfn-typegen.toml                # the types the service uses: `cfn-typegen --template original.json` lists them
    cfn_types/                      # generated, so it is gitignored (or committed, for a handful of types)
    patterns/
      sls.py                        # only after you drop the sumo dependency; until then it is `from cfn_typed_sumo import sls`
    stacks/
      ledger.py                     # the imported module, tidied: build(settings) -> cfn.Template
    main.py                         # cli.main({"ledger": StackSpec(build, out=..., stack_name=...)}, settings=Settings)
    originals/                      # scratch, gitignored: what each stage had when you ejected (dev.json, prod.json), fetched with get-template
    tests/
      test_ejection.py              # build(stage) == the original, for each stage
    rendered/
      ledger-dev.yaml               # one per stage, committed: the files that are reviewed and deployed, and the permanent pin
      ledger-prod.yaml
    pyproject.toml
```

Three decisions in it:

- **One original per stage.** A service deployed to `dev` and `prod` has two templates that differ in their values, and `STAGE` is
  an argument of `build`. The test pins each stage, so a stage you have not ejected yet is not blocked by one you have. The `parametrize` list in
  the test is the stages that are ejected.
- **The originals are scratch, `rendered/` is the pin.** `originals/` is for the ejection: fetch each stage with
  `aws cloudformation get-template --stack-name NAME-STAGE --template-stage Original`, keep the directory in `.gitignore`, and let the test skip
  when a file is absent, so it runs everywhere and bites where the files are (a CI job with read access fetches them first). Once the
  test passes, `rendered/ledger-dev.yaml` *is* the original in a different format, and from then on the golden-file test
  ([testing](../testing.md)) is what pins it: `assert_matches_file` in the test (below) fails on any change, and `CFN_TYPED_UPDATE=1` writes the file.
  Both hold the same values (bucket names, ARNs, sometimes an account ID inside an ARN), so what you may commit is the same for both: in a private
  repository, the rendered files; in a public one, replace the identifying values first, as the made-up `original.json` here does.
- **`serverless.yml` goes last.** Keep it, and keep deploying with it, until the new stack has deployed once with an empty change set. Then delete it, the
  `package.json` of its plugins, and the deploy script's `sls` lines, in a commit of their own.

The test is short:

```python
# cfn/tests/test_ejection.py
import json
from pathlib import Path

import pytest

from cfn_typed.testing import assert_matches_file
from main import Settings
from stacks.ledger import build

CFN = Path(__file__).parent.parent
STAGES = ["dev", "prod"]  # the stages that are ejected


@pytest.mark.parametrize("stage", STAGES)
def test_the_stack_renders_what_is_deployed(stage: str) -> None:
    original = CFN / "originals" / f"{stage}.json"
    if not original.exists():
        pytest.skip(f"no {original}: fetch it with get-template (see the ejecting guide)")
    assert build(Settings(stage=stage)) == json.loads(original.read_text())


@pytest.mark.parametrize("stage", STAGES)
def test_the_rendered_file_is_committed(stage: str) -> None:
    assert_matches_file(build(Settings(stage=stage)), CFN / "rendered" / f"ledger-{stage}.yaml")  # CFN_TYPED_UPDATE=1 writes it
```

and `main.py` is the [command line](../cli.md#settings-a-dataclass-whose-fields-are-flags) with `stage` as a flag, so `python main.py emit ledger --stage prod`
renders one stage (`-o rendered/ledger-prod.yaml` writes it) and `python main.py check ledger --stage prod --live --stack-name ledger-prod` checks it against the running stack.
Once the stack is ejected, `--deployed` is the same check as the test, against the live template, and does not need the originals at all.

## Take the template

```text
$ sls package
$ cp .serverless/cloudformation-template-update-stack.json original.json
```

For a service built with SAM, `sam build` does not expand the transform, so take the processed template of the deployed stack
instead: `aws cloudformation get-template --stack-name NAME --template-stage Processed`.

If the deploy script edits the package before it deploys (`sed -i "s/default-stage/$STAGE/g"` on the JSON, see
[below](#where-the-frameworks-variables-went)), the file that matters is the one that was deployed, not the one `sls package` wrote:
take it from the stack, `aws cloudformation get-template --stack-name NAME --template-stage Original`, so that the values are the real ones
and the test compares with what is running.

Only that file matters. It has the framework's logical IDs, `WorkerLambdaFunction`, `IamRoleLambdaExecution`,
`EventsRuleSchedule1`, and those IDs are what CloudFormation matches the live stack against.

## Generate the types and import

```text
$ cfn-typegen --template original.json --out cfn_types
wrote 8 resources in 5 modules to cfn_types
$ cfn-typed import original.json -o imported.py --types cfn_types
wrote imported.py
```

`cfn-typegen --template` reads the resource types the template uses and generates a typed factory for each, from the
CloudFormation registry schemas, so you get `lambda_.function`, `iam.role` and the rest for exactly this service. `import`
writes `build() -> cfn.Template` with those factories, and a plain dict where there is no type for something.

For a template from `sls package`, `cfn-typed import --sls original.json -o stack.py` goes further: where the framework's resources for a function,
an event, the role, the bucket or an API are exactly what `cfn_typed_sumo.sls` writes (see [below](#then-use-the-patterns)), the module
calls it, and everything else stays as the plain resources. Each call is tried against the template while importing and used only when it
renders the same resources, so the module still renders to the original, and the header lists what stayed plain.

The module renders back to the original. That is the first thing to pin, in the test suite and before you change a line:

```python
assert imported.build() == json.loads(Path("original.json").read_text())
```

This is also the check for the whole ejection. If it holds, the logical IDs, the properties and the outputs are
unchanged, and a deploy of this code has nothing to change.

## Reading the framework's output

The template looks like a pile, but the framework writes the same few shapes every time, and knowing them tells you
what to keep and what to move to a pattern.

| You see | It is | A pattern for it |
|---|---|---|
| `{Name}LogGroup`, `{Name}LambdaFunction`, `{Name}LambdaVersion{hash}` | one `functions:` entry, three resources | `function` (log group and role included) |
| `{Name}EventsRuleSchedule1` and `{Name}LambdaPermissionEventsRuleSchedule1` | a `schedule` event, the rule and its permission | `schedule` |
| `{Name}EventSourceMappingSQS{Queue}` | an `sqs` event | [SQS-triggered Lambda](../patterns/sqs-trigger.md) |
| `ApiGatewayRestApi`, `ApiGatewayResource…`, `ApiGatewayMethod…`, an `…Options` method per path | `http` events on REST API: a resource tree, and a mock `OPTIONS` method for CORS | keep as typed resources until you need to change them |
| `ApiGatewayApiKey1`, `ApiGatewayUsagePlan`, `ApiGatewayUsagePlanKey1` | `private: true` on a route | keep |
| `HttpApi`, `HttpApiStage`, `HttpApiRoute…`, `HttpApiIntegration…` | `httpApi` events | [HTTP API with a JWT authorizer](../patterns/http-api.md) |
| `ServerlessDeploymentBucket` and its policy | the packaging bucket | see the next section |
| `IamRoleLambdaExecution` | one role for every function in the service | see the next section |
| a type starting `Custom::` | a plugin's custom resource | copy it as it is |

Names carry the original key: the framework replaces `-` with `Dash` and `_` with `Underscore`, so a function called
`api_handler` is `ApiUnderscorehandlerLambdaFunction`. Keep that, since it is the logical ID.

Two things in the role are the framework's doing and not yours. It writes the log statements (`logs:CreateLogStream`,
`CreateLogGroup`, `TagResource`, `PutLogEvents`, scoped to the service prefix) itself, and it adds the statements
an event needs: an `sqs` event adds `sqs:ReceiveMessage`, `DeleteMessage` and `GetQueueAttributes`. Your
`iamRoleStatements` are the rest. When you replace the role, the second kind is what gets forgotten, and the first
time you notice is a function that stops reading its queue.

## Where the framework's variables went

If you have the `serverless.yml` and the deploy script, read them next to the template, because some values in it were put there
by steps you cannot see in the JSON.

The framework resolves every `${…}` on the machine that runs `sls`, before it builds the template. So whatever the
variable was, `original.json` holds the value it had that day, and ejecting from the template is safe. The table matters
for the next step: deciding what each one becomes in Python, so the values do not stay frozen.

| `serverless.yml` | What it reads | In Python |
|---|---|---|
| `${self:custom.x}`, `${self:provider.region}` | another key in the same file | a variable or function argument. This is the trivial one |
| `${opt:stage}`, `${opt:memory, 1024}` | a CLI flag, with a default | a field of a settings dataclass, which [`cfn_typed.cli`](../cli.md#settings-a-dataclass-whose-fields-are-flags) turns into `--stage` and `--memory 2048` |
| `${sls:stage}` | `${opt:stage, self:provider.stage, "dev"}` | a `stage` field in the [settings](../cli.md#settings-a-dataclass-whose-fields-are-flags), with `default="dev"` |
| `${sls:instanceId}` | a random id for each CLI run | `uuid.uuid4().hex`. It is used in `ApiGatewayDeployment${sls:instanceId}`, so copy the one from the template instead, as in [`deployment_id`](#then-use-the-patterns) |
| `${aws:region}`, `${aws:partition}` | `${opt:region, self:provider.region, "us-east-1"}`, and a lookup of the ARN prefix | a `region` argument, or `cfn.ref("AWS::Region")` and `cfn.ref("AWS::Partition")` when the value should be the deployed one |
| `${aws:accountId}` | an STS call with your credentials | `cfn.ref("AWS::AccountId")` or `${AWS::AccountId}` in `cfn.sub(...)`, which is better than a literal because it works in any account |
| `${env:NAME}`, `${env:NAME, default}` | the process environment, and `.env` and `.env.${stage}` files | `os.environ["NAME"]` (and `os.environ.get("NAME", default)`). Or a settings field with `metadata={"env": "NAME"}`: the flag, then the variable, then the default, and [required](../cli.md#settings-a-dataclass-whose-fields-are-flags) when it has none. The `.env` files need `python-dotenv` or an explicit load |
| `${file(./x.yml):key}`, `${file(./x.json)}` | a YAML or JSON file, a key or all of it | `yaml.safe_load` or `json.loads`, then index it. Often a whole `resources:` block moves into typed resources instead |
| `${file(./x.js):fn}`, `${file(./x.ts)}` | a JavaScript or TypeScript module, an export or a function that gets `options`, `resolveVariable` and `resolveConfigurationProperty` | an ordinary Python function. This is the case where Python is simply better: the code was always the point |
| `${param:domain}`, `stages.prod.params` | a value that is set per stage | a dict keyed by stage: `PARAMS[stage]["domain"]`, with `stage` a [settings](../cli.md#settings-a-dataclass-whose-fields-are-flags) field |
| `${strToBool(${ssm:X})}` | `"true"` or `"false"` (also `"0"`, `"1"`) to a boolean | `value.lower() in ("true", "1")`. Anything else was an error in the framework, so raise too |
| `${git:branch}`, `sha1`, `commit`, `message`, `describe`, `isDirty`, `user`, `email`, `repository`, `tags` | the checkout | `subprocess.run(["git", "rev-parse", "--short", "HEAD"], ...)`. Better as a settings field that CI passes in (`--sha $GITHUB_SHA`), so rendering does not depend on a checkout |
| `${ssm:/path}`, `${aws:ssm:/path}` | read at package time, from SSM Parameter Store or Secrets Manager | **pick one.** `params.ssm(...)` (an SSM-typed [parameter](../patterns/parameters.md)) or `cfn.dynamic_ssm("/path")` (`{{resolve:ssm:/path}}`) read it at deploy time, which is usually what you wanted. `boto3` at render time freezes the value in the template, the same as the framework did |
| `${cf:stack.Output}` | an output of another stack, read at package time | `cfn.import_value("Name")` if that stack exports it. Otherwise a `boto3` call at render time, or a parameter |
| `${s3:bucket/key}` | the text of an S3 object | `boto3`, at render time. Rare, and it freezes the value like `ssm` |
| `${terraform:outputs:name}`, `${vault:path.key}`, `${doppler:project/KEY}` | a Terraform state output, or a secret | the same as `ssm`: a parameter or a dynamic reference for secrets (never in the template text), a render-time call for the rest |
| `${service:other.Output}` | another service's output, in Serverless Compose only | an import value, or a parameter |
| `${a, b}` | the first one that exists | `x if x is not None else b`, or `dict.get` |
| `${file(./config.${sls:stage}.json):CREDS}` | a variable inside another | f-strings and function calls, so nesting is not a feature to translate |

The framework only substitutes in values, never in keys: no variable can make a logical ID. That is one thing
Python does better. A resource name built in a loop is just a string.

Three of these, `ssm`, `cf` and `s3`, need a decision and not a translation. The framework made a network call when
you ran `sls package`, and what is in the template is that answer. If you keep the literal, the template is the same as it
was, and a change in the parameter store does not reach the stack until you render again. If you switch to a deploy-time
reference, the template changes, which is what you want, and which a change set shows. Do it as a separate step from the ejection.

A few of these are described in more detail:

- **A `sed` for the region.** Some deploy scripts also run `sed -i "s/eu-west-1/$REGION/g"` on the package: a literal region
  that was typed somewhere in the service is replaced in the generated text, wherever it appears. Find where it was meant (an ARN,
  a bucket name) and make it the `region` argument; the same goes for an identity such as `default-identity` that the script fills in from a
  pipeline variable.
- **`${self:…}` and `${opt:…}`** are resolved when `sls package` runs, so the template holds the literal (`dev`,
  `eu-west-1`). These are the `SERVICE` and `STAGE` values in `eject.py`, and `STAGE` is a function argument if one
  file should render every stage.
- **`#{AWS::AccountId}`** is the `serverless-cf-vars` plugin: it rewrites `#{…}` to `${…}` so that `Fn::Sub` resolves it at deploy time.
  It is already `cfn.sub(...)` in the imported module.
- **`${file(path):field}`** is also package time: build metadata for tags, or per-stage settings such as subnet IDs.
  In Python they are a function argument, an environment variable, or a module you import.
- **`{{resolve:ssm:/path}}`** passes through untouched and CloudFormation resolves it at deploy time. Keep the string.
- **`default-*` placeholders and `sed`.** When one `sls package` output is deployed to several stages, the
  `serverless.yml` holds made-up values (`default-stage`, `default-kmskey`) and the deploy script runs
  `sed -i "s/default-stage/$STAGE/g"` on the JSON. That is a global string replacement on generated output: it breaks
  quietly if the placeholder shows up somewhere else, and a large service can have eight of them. Each becomes an
  argument to `build`, and nothing is substituted in the text. For many services this is the biggest gain of the whole move.
  The `sed` lines in the deploy script are the list of values to turn into arguments.

## Tidy by hand, keeping the IDs

An imported module is faithful and repetitive: `ledger` and `dev` are written into a dozen strings. The first pass
makes the repeated parts values, and nothing else:

```python
--8<-- "examples/serverless_eject/eject.py:names"
```

```python
--8<-- "examples/serverless_eject/eject.py:resources"
```

Everything that CloudFormation sees is the same: each resource keeps the ID the framework gave it, and the test
that compares `build()` with `original.json` still passes. That test is what lets you tidy without worrying. Change
something that shows in the template and it fails with the difference.

## Decide what the framework did for you

The framework does four things a template does not show, and ejecting means doing them or choosing not to.

| The framework | After ejecting |
|---|---|
| Packages the code and uploads it to `ServerlessDeploymentBucket` with a new key on every deploy | You upload the zip (`aws s3 cp`, your CI) and pass the key. The `S3Key` in the template is the one thing that changes per release |
| Adds a `AWS::Lambda::Version` with a hash in its logical ID on each deploy | That ID changes on every deploy, so it cannot be a fixed name. Drop it (`DeletionPolicy: Retain` kept the old versions), or use `live_alias` from [CDK L2 constructs](../patterns/cdk-l2.md#provisioned-concurrency-for-a-lambda) |
| Creates the deployment bucket and its policy | Keep it while `Code` points into it. Move the code to a bucket you own, then remove it in a later change |
| Builds IAM statements from `iamRoleStatements` | They are plain statements in the role. Typed [grants](../grants.md) replace the handwritten ones when you want them |

Each of these is a change to the template, and each shows up in a diff.

## What real services set

The example services here use the framework's defaults. Most real ones set something that changes the template, and these are the
ones found in a sample of real `serverless.yml` files:

| `serverless.yml` | What is different | In `sls.function` |
|---|---|---|
| no `functions:`, only `resources:` | the template is those resources, copied as they are: no role, no deployment bucket resource. Most of the simple stacks are a bucket and its policy | nothing to call. `import` (or `import --sls`, which says it found nothing and writes the same) is the whole job |
| `provider.deploymentBucket.name` | no `ServerlessDeploymentBucket`; `Code.S3Bucket` is that name, not a `Ref`, and the output holds the name | `bucket="name"`, and `sls.outputs(..., bucket="name")` |
| `provider.versionFunctions: false` | no `{Key}LambdaVersion`, so no hash to copy | `versioned=False` |
| `provider.iam.role: MyRole` | no `IamRoleLambdaExecution`; the role is yours, in `resources:`, and the function's `Role` points at it | `role=get_att("MyRole", "Arn")` |
| `functions.x.name: some-name` | the function is not `{service}-{stage}-{key}` | `name="some-name"` |
| `http` event `path: /{proxy+}`, `method: ANY`, `cors: true` | one REST method `ANY` on the `{proxy+}` resource, and its `OPTIONS` | `Route("/{proxy+}", "ANY", "app")` |
| `package.artifact: x.zip`, `individually: true` | the zip is yours, built outside the framework: its key in the bucket is the only thing that moves | `s3_key` |

`import --sls` handles all of them: it tries each call and writes it only when it renders what the template has, so a service
that combines two of them is still right.

## Python WSGI apps

A Flask or Django service that uses the `serverless-wsgi` plugin has `wsgi_handler.handler` as its Lambda handler, not
`serverless_wsgi.handler`. The plugin adds three files to the package when it packages, and none of them is in your code:

| File | Where it comes from |
|---|---|
| `wsgi_handler.py` | **only the plugin's npm package** (`npm pack serverless-wsgi` and take it from the tarball), not PyPI. Vendor it into your repo with the plugin's licence |
| `serverless_wsgi.py` | the PyPI package `serverless-wsgi`: install it with your dependencies, or vendor the file |
| `.serverless-wsgi` | JSON the plugin writes from `custom.wsgi.app`: `cfn_typed.packaging.wsgi_config("api.app")` writes it |

None of it is tied to the rest of Serverless, so the function runs unchanged once the three files are in the zip and `Handler`
stays `wsgi_handler.handler`. The danger is that **an empty change set cannot see them**: they live in the zip, and a package
that lacks one deploys cleanly and fails on the first request. Put a check in CI, after the build step that makes the zip:

```python
from cfn_typed.packaging import call_handler
from cfn_typed.testing import assert_wsgi_package_ok


def test_the_package_is_sound() -> None:
    assert_wsgi_package_ok("build/api.zip", app="api.app")       # all three files, and the app is a module in the zip
    reply = call_handler("build/api.zip", "wsgi_handler.handler", HEALTH_EVENT)   # the handler, once, in a fresh Python
    assert reply["statusCode"] == 200
```

`HEALTH_EVENT` is an API Gateway proxy event: copy a real one (the API Gateway console's test tab, or a log line) and shorten it. The
command line does the same: `cfn-typed zip build/api.zip --wsgi --app api.app --invoke event.json`. `.serverless-wsgi` is the plugin's file, so
compare `wsgi_config` with the one in a package from a real `sls package` before relying on it.

## Where the zip is

The template names the code by an S3 key in the deployment bucket, and a plugin's custom resource (the `existing: true` S3 bucket
one, for example) names its own zip there too. Keep those objects: if the key is gone, the next update of that function fails, and the
change set does not tell you. `check --code --bucket-name ServerlessDeploymentBucket=NAME` (or `assert_code_exists`) looks up every
S3 key the template reads and lists the missing ones. Run it before the first deploy from the new code ([advanced checks](#advanced-checks)).

## Then use the patterns

Most patterns pick their own logical IDs: `function` makes `Worker`, `WorkerRole` and `WorkerLogs`, not
`WorkerLambdaFunction`, `IamRoleLambdaExecution` and `WorkerLogGroup`, and a new ID is a replacement. For a service that
is already deployed, use `cfn_typed_sumo.sls`: the framework's resources, written under the framework's IDs.

```python
--8<-- "examples/serverless_eject/with_sls.py:stack"
```

`build()` renders to exactly `original.json`, and the test suite fails on any difference, so deploying it changes
nothing.

| Function | Writes | IDs |
|---|---|---|
| `sls.function(key, ...)` | a `functions:` entry, with `log_destination=` for log forwarding | `{Key}LogGroup`, `{Key}LambdaFunction`, `{Key}LambdaVersion{id}`, `{Key}LogSubscriptionFilter` |
| `sls.iam_role(service, stage, statements)` | the shared role. `log_actions=` is for a framework that wrote the log statement without `logs:TagResource` (versions 1 and 2) | `IamRoleLambdaExecution` |
| `sls.deployment_bucket()` | the packaging bucket and its policy | `ServerlessDeploymentBucket`, `ServerlessDeploymentBucketPolicy` |
| `sls.schedule_event(key, expression)` | a `schedule` event | `{Key}EventsRuleSchedule1`, `{Key}LambdaPermissionEventsRuleSchedule1` |
| `sls.sqs_event(key, queue)` and `sls.sqs_statement(queue)` | an `sqs` event, and the role statement the framework adds for it | `{Key}EventSourceMappingSQS{Queue}` |
| `sls.sns_event(key, topic)` | an `sns` event on a topic in the template: the subscription and its permission | `{Key}SnsSubscription{Name}`, `{Key}LambdaPermission{Name}SNS` |
| `sls.stream_event(key, stream, kind=...)` and `sls.stream_statement(kind, arn)` | a `stream` event (`dynamodb` or `kinesis`), and its role statement | `{Key}EventSourceMapping{Dynamodb\|Kinesis}{Name}` |
| `sls.function(..., vpc=sls.Vpc(...))` and `sls.vpc_statement()` | a function in a VPC, and the network interface statement the framework adds to the role | `VpcConfig` on `{Key}LambdaFunction` |
| `sls.rest_api(service, stage, [Route(...)])` | `http` events: the API, a resource per path segment, a method per route, a CORS `OPTIONS` per path, the deployment, the permissions, and the API key bundle for `private=True` routes. `binary_media_types=[...]` is `apiGateway.binaryMediaTypes` and goes on the API; `authorizers={...}` and `Route(authorizer=...)` write custom authorizers | `ApiGatewayRestApi`, `ApiGatewayResourceTodosIdVar`, `ApiGatewayMethodTodosIdVarGet`, `ApiGatewayMethodTodosOptions`, `ApiGatewayDeployment{id}`, `{Key}LambdaPermissionApiGateway`, `ApiGatewayApiKey1` |
| `sls.http_api(name, [HttpRoute(...)], authorizers=...)` | `httpApi` events with JWT authorizers | `HttpApi`, `HttpApiStage`, `HttpApiAuthorizer{Name}`, `HttpApiIntegration{Key}`, `HttpApiRouteGetUsersIdVar`, `{Key}LambdaPermissionHttpApi` |
| `sls.outputs(...)` and `sls.endpoint_outputs(...)` | the outputs the framework adds | `ServerlessDeploymentBucketName`, `{Key}LambdaFunctionQualifiedArn`, `ServiceEndpoint`, `HttpApiUrl` |

`sls.logical("api_handler")` gives `ApiUnderscorehandler`, the framework's rule for turning a key into a name, and
`sls.path_id("/todos/{id}")` gives `TodosIdVar`, its rule for a path.

A service with the usual events looks like this, from
[`with_sls_api.py`](https://github.com/vivainio/cfn-typed/blob/main/examples/serverless_eject/with_sls_api.py): a REST API,
an HTTP API behind a JWT authorizer, and an SQS consumer, that renders to exactly the made-up `original_api.json`:

```python
--8<-- "examples/serverless_eject/with_sls_api.py:stack"
```

Some arguments need a value from the template you are ejecting from, because the framework computes it:
`version_id` and `code_sha256` for each function, and `deployment_id` for the REST API's deployment (it is a timestamp). Copy them.
The IDs have to stay the same, and the next deploy that changes the code decides what the new ones are.

What is not here: `s3` and `cloudwatchLog` events, and custom domains (see the next section). They stay as typed resources from the `import`, and
the test that compares with the original keeps them honest. The authorizer, `sns`, `stream` and VPC pieces were written from the framework's
documentation and its usual output, not from a template of yours, so `import --sls` is the check: when it does not claim a group, the
group differs from what `sls` writes, and the plain resources are what to keep.
The two templates here are made up, in the shapes the framework writes, so check the IDs against one of
your own: `sls.function(...)` for a function, then `emit` and compare.

Moving a resource to a pattern with its own IDs is still a real change, which is fine for stateless things and
not for anything that holds data.

## Resources the framework made with API calls

A plugin can create a resource that is not in the template at all. `serverless-domain-manager` makes the API's custom domain and its
base path mapping with API calls, and the package has no trace of them. Ejecting such a service means putting them in the template, and
CloudFormation cannot create a domain that exists: it has to be imported (CloudFormation's resource import). `cfn_typed.adopt.resources_to_import`
builds the list, checking each identifier against the registry schemas, and `cfn_typed.changes.plan(..., resources_to_import=...)`
makes the IMPORT change set. It is rare (one service in a sample of fifty used the plugin), so there is no command for it.

## When the runtime is already dead

The check says which runtimes are past their dates (`cfn-typed check`), and for a runtime AWS no longer lets you update it says so:
`nodejs8.10`, `python2.7` and `dotnetcore2.1` can be neither created nor updated. An ejection with an unchanged template never calls
`UpdateFunction`, so the first deploy is safe, and the function keeps running. The block bites on the first change to the function
(new code, memory, an environment variable): that deploy fails. So eject first, with an empty change set, and move the runtime as its own
change, which is a Python or Node upgrade with its own testing. A runtime that is only deprecated is a warning, with a date.

## The version of the framework

A template from Serverless 1 or 2 differs from a version 3 one in details, so do not assume the shapes above. Known: the role's log
statement has no `logs:TagResource` (`iam_role(log_actions=[...])`). The rest you find by importing: `import --sls` claims what matches
and leaves the rest as plain resources. A service with its own `stackName` deploys under that name: give the stack
`StackSpec(build, stack_name="...")` so `check --plan` and `check --deployed` look at the right one.

## Try it on one real stack first

The two example templates here are made up, and the tests prove the tools against those only. Before trusting any of it, run the
whole procedure on one real stack, which costs nothing because nothing is executed:

```text
$ aws cloudformation get-template --stack-name NAME --template-stage Processed > original.json
$ cfn-typed import --sls original.json -o stack.py        # then the tests: build() == original.json
$ python stacks.py check ledger --deployed --plan --stack-name NAME --template-stage Processed   # rendered vs running; a change set, never executed, that should say no changes
```

`--deployed` says where the rendered template and the live one differ, and `--plan` stops on a stateful resource that would be replaced. When both are clean, the
ejection is exact for that stack. Start with one of the S3-only stacks, and keep a copy of the real `original.json`, with the
account IDs and names replaced, as the test fixture for the services like it.

## Dropping the sumo dependency

`cfn-typed-sumo` is a good place to start, and a poor thing to keep: its helpers can change between releases, and the template of a
running service should change when you decide. Once the ejected services deploy cleanly, with an empty change set and the tests
that compare `build()` with the original passing, cut the dependency in three steps. Each leaves the rendered templates unchanged,
which the tests prove.

1. **Copy `sls.py`** from `packages/sumo/src/cfn_typed_sumo/` into your own `patterns/` directory (`cfn/patterns/sls.py`, in [the project layout](../project-layout.md)). It depends only on `cfn-typed`
   and on the generated types of a few services, so there is nothing else to untangle. Copy `tests/test_sls.py` with it.
2. **Generate the types it imports, yourself.** `sls.py` has no types of its own: there is no "sls" module to generate. It imports the
   ordinary registry types of eight services (the `from cfn_typed_sumo.types import apigateway, apigatewayv2, events, iam, lambda_,
   logs, s3, sns` at the top), which `cfn-typegen` makes for any project. Put them in your `cfn-typegen.toml`, with the templates of the services you
   ejected, so that their other resources (a queue, a table) get factories in the same package:

   ```toml
   # cfn/cfn-typegen.toml: `cfn-typegen --config cfn/cfn-typegen.toml` writes cfn/cfn_types/
   out = "cfn_types"
   docs = false
   types = [
       # what patterns/sls.py imports
       "AWS::ApiGateway::*",
       "AWS::ApiGatewayV2::*",
       "AWS::Events::Rule",
       "AWS::IAM::Role",
       "AWS::Lambda::*",
       "AWS::Logs::*",
       "AWS::S3::Bucket*",
       "AWS::SNS::Subscription",
   ]
   # what each ejected service's own template uses
   templates = ["../services/ledger/original.json", "../services/shop/original.json"]
   ```

   Then change the imports. In `patterns/sls.py`, `from cfn_typed_sumo.types import (...)` becomes `from cfn_types import (...)`. In each stack
   module, `from cfn_typed_sumo import sls` becomes `from patterns import sls`, and `from cfn_typed_sumo.types import sqs` becomes `from cfn_types import sqs`.
   Commit the toml, and either commit the generated files or generate them in CI
   ([the choice is described here](../sumo.md#recommended-start-with-sumo-then-eject-what-you-use)).
3. **Run what proves it.** The tests that compare `build()` with `original.json` for each service, `emit` before and after, and
   `ty check`. Then remove `cfn-typed-sumo` from the dependencies, so that no import slips back.

`import --sls` is a one-time tool and does not need to be copied: use it while you are ejecting
(`uvx --with cfn-typed-sumo cfn-typed import --sls original.json -o stack.py` runs it without adding the package to the project), and the
module it writes needs only your copy of `sls.py`. A service you eject later, after dropping the dependency, can run it the same way.
You can also stop at any point: a service that works with sumo's helpers can keep them until you want to change one.
[Start with sumo, then eject what you use](../sumo.md#recommended-start-with-sumo-then-eject-what-you-use) is the general version of this.

## Advanced checks

An empty change set only proves that CloudFormation sees no change. These checks ask what it cannot see: the live template, what a
deploy would destroy, and the code behind the template. They are opt-in because they call AWS; plain `check` stays offline.
Use them in this order on each service, and stop at the first one that reports something.

| Check | Asks | Finds |
|---|---|---|
| `check --deployed` | `aws cloudformation get-template` | where the template your code renders differs from the one the stack has, by path in the template. This is the live version of the test that compares `build()` with `original.json` |
| `check --plan` | `aws cloudformation create-change-set`, then `describe-change-set`, then `delete-change-set` | a stateful resource (table, bucket, queue, key, distribution, log group, database) that a deploy would replace or remove. It prints the change set, and exits 1 on such a change. The change set is never executed |
| `check --code` | `aws s3api head-object`, once per distinct object | a function or layer whose S3 zip is not there: the deployment bucket's cleaned-up keys, a plugin's custom resource zip |
| `zip` | nothing: it reads a file | a package zip that lacks files (the wsgi trio, a handler that does not exist), and with `--invoke` a handler that fails when called once |
| `check --retention` | nothing: it reads the template | a stateful resource with no `Retain` or `Snapshot` policy, which a later removal or replacement would destroy |

`--live` is `--deployed --plan --code` together. The stack is named like the stack here, unless it has
`StackSpec(build, stack_name="...")` or you pass `--stack-name` (a service that set its own `stackName`).

```text
$ python stacks.py check ledger --live --stack-name ledger-dev --bucket-name ServerlessDeploymentBucket=ledger-dev-serverlessdeploymentbucket-abc
```

**How they use AWS.** Each one runs the `aws` command line as a subprocess: there is no boto3 and cfn-typed never reads credentials. It
uses whatever `aws` resolves (environment variables, a profile, SSO), and `--aws-profile` and `--aws-region` are passed on. A command that
fails (no such stack, no permission) exits 2, which says the check could not run, not that the template is wrong. The permissions needed
are `cloudformation:GetTemplate` for `--deployed`; `CreateChangeSet`, `DescribeChangeSet` and `DeleteChangeSet` for `--plan`; and
`s3:GetObject` on the zips for `--code`.

**What to know before running them.**

- `--plan` is the only one that is not purely a read: it creates a change set and deletes it again. The stack is untouched. If the
  process dies in between, a harmless change set is left behind (`--keep-change-set` leaves it on purpose, for you to read in CloudFormation). It sends
  the template inline, so it must be under 51,200 bytes, and a stack that is in the middle of an update cannot have one.
- `--code` treats any failure of `head-object` as a missing object, including a permission error, so a role that cannot read the
  deployment bucket sees every zip as missing. A bucket that is a `Ref` needs its real name from `--bucket-name LOGICAL=NAME`; it is
  reported and not guessed.
- `--deployed` compares the whole template, including `Description` and `Metadata`. Take the original from the same stage you
  rendered against (`--template-stage Processed` for a SAM stack, after the transforms have run), and expect differences for
  anything the deploy script `sed`s into the package.
- `zip --invoke` runs the code in the zip, in a fresh Python on your machine: use it on a package you built.
- None of these has been run against a real stack by the people who wrote them: the tests use a stand-in for `aws`. The first run on a real
  stack is the real test, so make it an S3-only one, as [below](#try-it-on-one-real-stack-first).

The same checks are Python functions for your test suite (`find_deployed_differences`, `find_change_problems`, `find_missing_code`, `find_zip_problems`,
`find_wsgi_problems` and `find_retention_problems`, and the `assert_*` forms in `cfn_typed.testing`). The command line is
[`check --live` and `zip`](../cli.md#check-live-ask-aws-about-a-stack-that-is-already-deployed).

## Deploy to the same stack

Use the stack name the framework used (`ledger-dev`, the service and the stage), and do not run `sls remove`: it
deletes the stack.

```text
$ aws cloudformation deploy --stack-name ledger-dev --template-file ledger.yaml \
    --capabilities CAPABILITY_NAMED_IAM --no-execute-changeset
$ aws cloudformation describe-change-set --stack-name ledger-dev --change-set-name <name from the output>
```

`python stacks.py check --plan ledger` (the [command line](../cli.md#check-live-ask-aws-about-a-stack-that-is-already-deployed) of your stack script) does the same without leaving a change set behind, prints the changes and exits 1 when a
table, bucket, queue, key, distribution or database would be replaced or removed.

Read the change set before executing it. An empty one means the ejection is exact. A resource marked `Replacement` is
a logical ID or an immutable property that changed, and you decide whether that is fine for it.

!!! note
    The example was checked by rendering and comparing, in the tests, and not against a real stack. The framework's
    template here is made up in the framework's style. A real one has more in it (API Gateway, event source mappings,
    custom resources), and the types for them come from the same `cfn-typegen --template`.
