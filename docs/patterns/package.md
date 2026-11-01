# Uploading code: `aws cloudformation package`

SAM and the Serverless Framework both zip your code and upload it to S3 as part of deploying. cfn-typed does not.
`emit` renders a template and nothing else: no network, no credentials, no build. So if you are coming from
SAM or Serverless, the question is where the upload went.

It is a step of its own in the AWS CLI, and it runs after you render and before you deploy:

```text
$ python -m stacks emit                      # render, as before
$ aws cloudformation package \
    --template-file rendered/worker.yaml \
    --s3-bucket my-artifacts \
    --s3-prefix worker \
    --output-template-file packaged/worker.yaml
$ aws cloudformation deploy \
    --template-file packaged/worker.yaml \
    --stack-name worker \
    --capabilities CAPABILITY_IAM
```

`sam package` and `sls package` are this same step under other names. SAM's is a wrapper around the CloudFormation
one, and `sam deploy` runs it for you.

## What `package` does

It reads a template, looks for properties that can point at local files, and for each one it finds:

1. zips the directory (a file is uploaded as it is),
2. uploads it to the bucket under a key that is a hash of the contents,
3. writes a copy of the template where the local path is replaced by the S3 location.

Because the key is a hash, code that did not change is not uploaded again, and the packaged template does not change
either. The code is only replaced in the stack when its contents change, which is what you want from a deploy.
(`--force-upload` uploads again regardless.)

The properties it knows about include `Code` on `AWS::Lambda::Function`, `Content` on `AWS::Lambda::LayerVersion`,
`CodeUri` on `AWS::Serverless::Function`, `DefinitionS3Location` on state machines, `BodyS3Location` on REST APIs, and
`TemplateURL` on nested stacks. Check `aws cloudformation package help` for your CLI version; anything not on its list is
left as written.

Paths are relative to the template file you pass, not to where you run the command. Render the template next to the code
or adjust the path, as for [SAM's `CodeUri`](sam.md).

## What it does not do

- **It does not build.** It zips what is in the directory. Installing dependencies, compiling, or bundling happens
  before, in whatever you use for that (a `pip install -t`, `npm ci`, a Docker build). `sam build` is the one SAM
  step that has no replacement here.
- **It does not create the bucket.** It must exist, in the region you deploy to.
- **It does not deploy.** `package` only writes a template. `deploy` is a separate command and a separate decision.
- **It leaves your rendered file alone.** The local path stays in `rendered/`, so the committed file does not change
  per release, and the diff stays about the infrastructure. The packaged copy is an output of CI, not something to commit.

## Where the code is

`cfn_typed.code` has one constructor for each place a function's code can be, and `function` (and anything that
takes a `lambda_.FunctionCode`) accepts all of them:

```python
from cfn_typed import code
from cfn_typed_sumo.constructs import function

function("Worker", code=code.s3("my-artifacts", f"worker/{build_id}.zip"), handler="app.handler", runtime="python3.13")
function("Worker", code=code.local("dist/worker.zip"), ...)       # for aws cloudformation package
function("Worker", code=code.inline("def handler(e, c): ..."), handler="index.handler", ...)
function("Worker", code=code.inline_file(HERE / "worker.py"), handler="index.handler", ...)
```

| | Renders | Needs |
|---|---|---|
| `code.s3(bucket, key)` | `S3Bucket`, `S3Key` | the zip is in S3 before `deploy` |
| `code.local(path)` | the path, as a string | `aws cloudformation package` before `deploy` |
| `code.inline(source)` | `ZipFile` | nothing, but small and without dependencies |
| `code.inline_file(path)` | `ZipFile`, read from the file at render time | the same |

**`code.s3`** is the one to use when your build already uploads the zip. The template only needs the bucket and the
key, which the build knows, and CloudFormation reads the object itself, so nothing is downloaded. Use a key that is
new for each build (a git SHA, a build number, a hash): Lambda updates only when `Code` changes, so overwriting the same
key does nothing. On a versioned bucket you can pass `version=` instead. The deploying identity needs `s3:GetObject`.
The bucket must be in the stack's region (see below). Both arguments take [intrinsics](../intrinsics.md), so the key can be a
parameter and the rendered file does not change per release.

**`code.inline` and `code.inline_file`** put the source text itself in the template, and CloudFormation zips it. The
name `ZipFile` is misleading: it is not a zip. The file is written as `index.py` (or `index.js`), so the handler
is `index.handler`, the source is limited to 4096 characters, and it can use only what the runtime provides (`boto3`
is there). With `inline_file` the source stays a real file you can lint and test; it is read when you render, a syntax error in a
`.py` file fails then, and the template stays self-contained, with no upload. Anchor a relative path with
`Path(__file__).parent`. It is one file, so it cannot import your other modules.

**`code.local`** renders a plain string, which is what `package` looks for, and is typed as a `FunctionCode` so it
passes where one is expected. It is not one until `package` has replaced it, so the rendered file cannot be deployed as it is.
For SAM's `Function`, `CodeUri="src/"` is already a `str`, and needs no helper.

## The bucket must be in the function's region

Bucket names are global, but every bucket lives in one region, and Lambda requires the code bucket to be in the same
region as the function. (A bucket in another account is fine, with a bucket policy.) A bucket in the wrong region is
not found at render time: it fails during `deploy`, when Lambda fetches the code.

For a stack that goes to several regions, upload the same zip to one bucket per region, with the region in the name, and
let the template pick it:

```python
from cfn_typed import code, sub

code.s3(sub("my-artifacts-${AWS::Region}"), key)
```

The key is the same in every bucket, so the rendered templates differ only by that substitution. `aws cloudformation
package` has the same rule: its `--s3-bucket` must be in the region you deploy to, so run it once per region.
For a single region, a plain bucket name is all you need.

## Keep the uploaded code after you deploy

The object only has to exist while CloudFormation creates or updates the function, because Lambda copies the code
into its own storage then. Deleting it afterwards does not affect the running function. It does affect these:

- **Rollback.** When an update fails, CloudFormation restores the previous `Code`, which means fetching the previous
  object. If that is gone, the rollback fails too, and the stack is left in `UPDATE_ROLLBACK_FAILED`, which takes
  work to recover from.
- **Replacement.** Renaming the function, or changing a property that forces a new one, creates it from the
  template's `Code`.
- **Redeploying an older template.** Its `Code` points at a key that no longer exists.

Redeploying the same template changes nothing and fetches nothing, so it is not affected.

So do not delete a build right after deploying it. Let a bucket lifecycle rule expire objects after a few weeks, or keep
the last few builds per function. The zips are small, and this keeps rollback and going back to a recent version working.
This applies to `code.s3` and to what `package` uploads. `code.inline` is not affected, because the source is in
the template.

## In CI

The three commands are three steps, and each can run alone:

| Step | Needs | Safe to repeat |
|---|---|---|
| `emit`, `diff` | nothing | yes |
| `package` | S3 write access | yes, an unchanged artifact is not uploaded again |
| `deploy` | CloudFormation and IAM | creates a change set |

A pull request can run the first one. The pipeline that deploys runs all three, and you can look at
`packaged/worker.yaml` before the last one if you want to see what is about to go out.

## A release flow for plain CloudFormation

If you are moving off SAM or the Serverless Framework, `sam deploy` and `sls deploy` did four things at once: build,
upload, render and deploy. Plain CloudFormation has them as separate steps, which is more to write once and easier to
reason about afterwards.

The premise is **one build result, deployed from there to several regions** (and stages). You build and render once. The
build result is the zip and the template, and a deploy takes that result and puts the zip where the target region
can read it. Nothing is rebuilt or re-rendered per region. This flow works well with [`code.s3`](#where-the-code-is).

This skips `aws cloudformation package`. That command rewrites a template for one bucket in one region, which is the opposite
of a build result you reuse: the packaged template is tied to the bucket it was uploaded to. Here the upload is a copy you
control, and the template already holds the bucket and key.

**Build, once per commit**

1. Build the zip.
2. Choose the key from the build, such as `worker/<git-sha>.zip`.
3. Render the template with that key. The bucket is `sub("deploy-artifacts-${AWS::Region}")`, so one template
   serves every region.
4. Keep the zip and the rendered template together as the build artifact.

```python
def build(key: str) -> Template:
    ...
    function("Worker", code=code.s3(sub("deploy-artifacts-${AWS::Region}"), key), handler="app.handler", runtime="python3.13")
```

**Deploy, for each stage and region**

1. Copy the zip from the build artifact into that region's bucket, under the same key.
2. Check that it is there.
3. Deploy the rendered template in that region.

```text
aws s3 cp dist/worker.zip s3://deploy-artifacts-$REGION/worker/$SHA.zip --region $REGION
aws s3api head-object --bucket deploy-artifacts-$REGION --key worker/$SHA.zip --region $REGION
aws cloudformation deploy --region $REGION --template-file rendered/worker.yaml --stack-name worker-$STAGE \
    --parameter-overrides Stage=$STAGE --capabilities CAPABILITY_IAM
```

If the build artifacts are in S3 as well, `aws s3 cp s3://build-bucket/key s3://deploy-artifacts-$REGION/key` copies
between buckets without downloading (for another region it needs `--source-region`).

Why it is arranged this way:

- **Render once.** What you tested is what you deploy. Everything that differs between stages (names, sizes,
  subnets) is a [parameter](parameters.md) and not a re-render.
- **The key is the identity of the build.** The same key in every regional bucket means the template needs no
  per-region edits, and the diff of a release is the one key.
- **The copy is the only step that writes to the deploy bucket.** Give the deploying role write access to its regional bucket
  and nothing else, and read access on the build artifact.
- **Keep the old builds** in each regional bucket for [rollback](#keep-the-uploaded-code-after-you-deploy).

If the code is small enough to [inline](#where-the-code-is), none of this is needed: the code is in the template, and
the template is the whole release.
