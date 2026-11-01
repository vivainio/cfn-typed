# Ejecting from the Serverless Framework

!!! note "Two kinds of ejecting"
    This page is about leaving the Serverless Framework (or SAM) for a service that is already deployed. Moving
    patterns you used from `cfn-typed-sumo` into your own package is a different thing, described in
    [cfn-typed-sumo](../sumo.md#recommended-start-with-sumo-then-eject-what-you-use).

The [Serverless Framework in a few lines](../patterns/serverless.md) page shows what a `functions:` entry becomes as patterns. This page
is for a service that already runs: you want to stop using the framework for it, and you do not want CloudFormation to
replace anything when you do.

The framework is a template generator, and `sls package` writes what it generates. So ejecting is not a rewrite
from the YAML. It is taking that template, turning it into Python that renders to exactly the same template, and then
changing it from there. The example is made up: a `ledger` service with one scheduled Python function, in
[`examples/serverless_eject`](https://github.com/vivainio/cfn-typed/tree/main/examples/serverless_eject). Its
`original.json` is written the way `sls package` writes one, with the framework's names, but it did not come from a real run
and nothing in it is from a real account.

## Take the template

```text
$ sls package
$ cp .serverless/cloudformation-template-update-stack.json original.json
```

For a service built with SAM, `sam build` does not expand the transform, so take the processed template of the deployed stack
instead: `aws cloudformation get-template --stack-name NAME --template-stage Processed`.

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
| `${sls:stage}` | `${opt:stage, self:provider.stage, "dev"}` | the `stage` argument |
| `${sls:instanceId}` | a random id for each CLI run | `uuid.uuid4().hex`. It is used in `ApiGatewayDeployment${sls:instanceId}`, so copy the one from the template instead, as in [`deployment_id`](#then-use-the-patterns) |
| `${aws:region}`, `${aws:partition}` | `${opt:region, self:provider.region, "us-east-1"}`, and a lookup of the ARN prefix | a `region` argument, or `cfn.ref("AWS::Region")` and `cfn.ref("AWS::Partition")` when the value should be the deployed one |
| `${aws:accountId}` | an STS call with your credentials | `cfn.ref("AWS::AccountId")` or `${AWS::AccountId}` in `cfn.sub(...)`, which is better than a literal because it works in any account |
| `${env:NAME}`, `${env:NAME, default}` | the process environment, and `.env` and `.env.${stage}` files | `os.environ["NAME"]` (and `os.environ.get("NAME", default)`). The `.env` files need `python-dotenv` or an explicit load |
| `${file(./x.yml):key}`, `${file(./x.json)}` | a YAML or JSON file, a key or all of it | `yaml.safe_load` or `json.loads`, then index it. Often a whole `resources:` block moves into typed resources instead |
| `${file(./x.js):fn}`, `${file(./x.ts)}` | a JavaScript or TypeScript module, an export or a function that gets `options`, `resolveVariable` and `resolveConfigurationProperty` | an ordinary Python function. This is the case where Python is simply better: the code was always the point |
| `${param:domain}`, `stages.prod.params` | a value that is set per stage | a dict keyed by stage: `PARAMS[stage]["domain"]` |
| `${strToBool(${ssm:X})}` | `"true"` or `"false"` (also `"0"`, `"1"`) to a boolean | `value.lower() in ("true", "1")`. Anything else was an error in the framework, so raise too |
| `${git:branch}`, `sha1`, `commit`, `message`, `describe`, `isDirty`, `user`, `email`, `repository`, `tags` | the checkout | `subprocess.run(["git", "rev-parse", "--short", "HEAD"], ...)`. Better as an argument that CI passes in, so rendering does not depend on a checkout |
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

!!! tip "`serverless_wsgi.py` is not part of the framework"
    Many Python apps (Flask, Django) have `serverless_wsgi.handler` as their Lambda handler. That file comes from
    the `serverless-wsgi` plugin, which copies it into the package at deploy time, but it is a trivial standalone
    wrapper that turns API Gateway events into WSGI calls. It is not tied to any part of Serverless. Put
    `serverless_wsgi.py` in your package yourself (vendor the file, or `pip install serverless-wsgi` and bundle it with your
    dependencies), keep `Handler` as it is, and the function runs unchanged after the ejection. Check that the plugin's
    `wsgi.app` setting, which `serverless.yml` writes into `.serverless-wsgi` in the package, is replaced by that
    file in your package too, since the wrapper reads the app's location from it.

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
| `sls.iam_role(service, stage, statements)` | the shared role | `IamRoleLambdaExecution` |
| `sls.deployment_bucket()` | the packaging bucket and its policy | `ServerlessDeploymentBucket`, `ServerlessDeploymentBucketPolicy` |
| `sls.schedule_event(key, expression)` | a `schedule` event | `{Key}EventsRuleSchedule1`, `{Key}LambdaPermissionEventsRuleSchedule1` |
| `sls.sqs_event(key, queue)` and `sls.sqs_statement(queue)` | an `sqs` event, and the role statement the framework adds for it | `{Key}EventSourceMappingSQS{Queue}` |
| `sls.rest_api(service, stage, [Route(...)])` | `http` events: the API, a resource per path segment, a method per route, a CORS `OPTIONS` per path, the deployment, the permissions, and the API key bundle for `private=True` routes | `ApiGatewayRestApi`, `ApiGatewayResourceTodosIdVar`, `ApiGatewayMethodTodosIdVarGet`, `ApiGatewayMethodTodosOptions`, `ApiGatewayDeployment{id}`, `{Key}LambdaPermissionApiGateway`, `ApiGatewayApiKey1` |
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

What is not here: `sns`, `stream`, `s3` and `cloudwatchLog` events, request authorizers on a REST API, and
custom domains. They stay as typed resources from the `import`, and the test that compares with the original keeps them honest.
The two templates here are made up, in the shapes the framework writes, so check the IDs against one of
your own: `sls.function(...)` for a function, then `emit` and compare.

Moving a resource to a pattern with its own IDs is still a real change, which is fine for stateless things and
not for anything that holds data.

## Deploy to the same stack

Use the stack name the framework used (`ledger-dev`, the service and the stage), and do not run `sls remove`: it
deletes the stack.

```text
$ aws cloudformation deploy --stack-name ledger-dev --template-file ledger.yaml \
    --capabilities CAPABILITY_NAMED_IAM --no-execute-changeset
$ aws cloudformation describe-change-set --stack-name ledger-dev --change-set-name <name from the output>
```

Read the change set before executing it. An empty one means the ejection is exact. A resource marked `Replacement` is
a logical ID or an immutable property that changed, and you decide whether that is fine for it.

!!! note
    The example was checked by rendering and comparing, in the tests, and not against a real stack. The framework's
    template here is made up in the framework's style. A real one has more in it (API Gateway, event source mappings,
    custom resources), and the types for them come from the same `cfn-typegen --template`.
