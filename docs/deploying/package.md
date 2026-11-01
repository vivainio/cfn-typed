# Uploading code and releasing

SAM and the Serverless Framework both zip your code and upload it to S3 as part of deploying. cfn-typed does not.
`emit` renders a template and nothing else: no network, no credentials, no build. So if you are coming from
SAM or Serverless, the question is where the upload went.

A function's code has to reach CloudFormation one of three ways, and this page covers each:

- **`aws cloudformation package`** uploads local files and rewrites the template ([below](#one-way-aws-cloudformation-package)).
- **You upload it yourself** and the template names the bucket and key ([`code.s3`](#where-the-code-is)). This is the
  better fit for a build you deploy to several regions, and it is what the example [release flow](#an-example-release-flow-for-plain-cloudformation)
  at the end of the page uses.
- **The source is in the template** ([`code.inline`](#where-the-code-is)), for small functions.

## One way: `aws cloudformation package`

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

## An example release flow for plain CloudFormation

This is one example of a flow, to show the parts and how they fit. Your build system, buckets and naming will differ,
and that is fine: what matters is that each part is a step you can see and change.

If you are moving off SAM or the Serverless Framework, `sam deploy` and `sls deploy` did four things at once: build,
upload, render and deploy. Plain CloudFormation has them as separate steps, which is more to write once and easier to
reason about afterwards.

The premise is **one build result, deployed from there to several regions** (and stages). You build once. The
build result is the zips, and a deploy takes them and puts each where the target region can read it. Nothing is
rebuilt per region. The template does not change per release either: it is rendered and committed like any other, and
the build's keys reach it as stack parameters. This flow works well with [`code.s3`](#where-the-code-is).

This skips `aws cloudformation package`. That command rewrites a template for one bucket in one region, which is the opposite
of a build result you reuse: the packaged template is tied to the bucket it was uploaded to. Here the upload is a copy you
control, and the template holds the bucket and a parameter for the key.

**Build, once per commit**

1. Build each zip (`worker.zip`, `api.zip`, ...).
2. Upload each to the build bucket under a key from the build, such as `worker/$SHA.zip`.

```text
for pkg in worker api; do
  aws s3 cp dist/$pkg.zip s3://build-artifacts/$pkg/$SHA.zip
done
```

**The template: one key parameter for each package**

```python
params = Params()
worker_key = params.string("WorkerCodeKey")      # no default: a deploy without it fails
api_key = params.string("ApiCodeKey")
bucket = sub("deploy-artifacts-${AWS::Region}")  # one template serves every region

function("Worker", code=code.s3(bucket, worker_key), handler="app.handler", runtime="python3.13")
function("Api", code=code.s3(bucket, api_key), handler="api.handler", runtime="python3.13")
```

**Deploy, for each stage and region**

1. Copy each zip from the build bucket into that region's bucket, under the same key.
2. Check that each is there.
3. Deploy the committed template with the keys as parameters.

```text
for pkg in worker api; do
  aws s3 cp s3://build-artifacts/$pkg/$SHA.zip s3://deploy-artifacts-$REGION/$pkg/$SHA.zip --source-region $BUILD_REGION --region $REGION
  aws s3api head-object --bucket deploy-artifacts-$REGION --key $pkg/$SHA.zip --region $REGION
done
aws cloudformation deploy --region $REGION --template-file rendered/app.yaml --stack-name app-$STAGE \
    --parameter-overrides WorkerCodeKey=worker/$SHA.zip ApiCodeKey=api/$SHA.zip Stage=$STAGE \
    --capabilities CAPABILITY_IAM
```

**The deploy job never downloads a package.** `aws s3 cp` between two buckets is a copy inside S3, so the zips do not pass
through the pipeline runner, and the only things it handles are keys. This is the way I recommend, because the deploy
job decides what goes where and the build only needs write access to its own bucket. There are two other ways to get the
zip into each region:

- **Upload to every region from the build.** The last build step pushes each zip to all the regional buckets, and the deploy
  job only checks and deploys. Deploys are faster, but the build needs write access to every regional bucket.
- **S3 replication.** The build uploads once and replication rules copy to the regional buckets. Replication is
  asynchronous, so the check before `deploy` has to retry until the object appears.

Why it is arranged this way:

- **The template does not change per release.** It is rendered and committed, and what changes is the parameters.
- **The same keys in every regional bucket** mean the template needs no per-region edits.
- **The record of a release is the stack's parameters, not a diff.** The keys are not in `rendered/`, so log them in CI
  or tag the stack with the SHA.
- **The copy is the only step that writes to the deploy bucket.** Give the deploying role write access to its regional bucket
  and nothing else, and read access on the build bucket.
- **Keep the old builds** in each regional bucket for [rollback](#keep-the-uploaded-code-after-you-deploy). Rollback
  restores the previous parameter values with the previous template, so each previous key must still exist.
- **Do not read the keys from SSM with a dynamic reference.** I believe CloudFormation does not see a changed
  resolved value when the template and parameters are the same, so the functions would not update. Pass the keys
  as parameters.

### A variation: key the deploy bucket by content

In the example, every release gives every package a new key (it has the commit in it), so every function updates on
every release, even one whose code did not change. If that matters to you, the build bucket can stay keyed by release
(it is how you find what a build produced) and the deploy bucket can be keyed by the content of the zip instead. A
package whose bytes did not change then keeps its key, and CloudFormation does not touch that function.

The build computes a hash for each package, however you like, and stores it where the deployment can read it. The hash
does not have to be of the zip's bytes, only a value that changes when the code changes. The simplest place to put it is
on the zip itself, as custom S3 metadata, so there is no second file to keep in step:

```text
# build
for pkg in worker api; do
  hash=$(sha256sum dist/$pkg.zip | cut -c1-16)              # or hash the sources and lockfile; shasum -a 256 on macOS
  aws s3 cp dist/$pkg.zip s3://build-artifacts/$pkg/$SHA.zip --metadata hash=$hash
done

# deploy
for pkg in worker api; do
  hash=$(aws s3api head-object --bucket build-artifacts --key $pkg/$SHA.zip --query Metadata.hash --output text)
  aws s3 cp s3://build-artifacts/$pkg/$SHA.zip s3://deploy-artifacts-$REGION/$pkg/$hash.zip --source-region $BUILD_REGION --region $REGION
  eval "$pkg=$hash"
done
aws cloudformation deploy ... --parameter-overrides WorkerCodeKey=worker/$worker.zip ApiCodeKey=api/$api.zip ...
```

`head-object` returns the metadata without downloading the zip. Metadata is set when the object is uploaded and cannot
be changed afterwards without copying the object over itself, its names are lowercase, and it is limited to about 2 KB, which
a hash fits easily. A manifest file, a tag, or a row in a database all work as well: the deployment only sees the stored
value, so it does not matter where it lives.

Things that change with it:

- **The zip does not need to be reproducible.** If you hash the zip's bytes, a rebuild with timestamps in it gets a new
  hash and one extra update, which is harmless. If you want to avoid that, hash the inputs instead: the source files
  and the lockfile, say. The deployment only sees the stored value, so it does not matter how it was made.
- **The hash must cover everything that goes into the zip.** A hash that misses an input (an unpinned dependency, a
  generated file) stays the same when the code does not, and the function is not updated. That is the one way this
  variation fails quietly.
- **A key no longer says which commit it came from.** Log the keys or tag the stack with the SHA. The build bucket's
  object for that commit holds the hash, so it is the link back.
- **Age-based lifecycle rules need care.** An unchanged package stays in use for many releases, so a rule can expire an
  object a running stack still points at. If the copy runs on every deploy and does not skip an existing object, it
  makes the object new again, so the age counts from the last deploy that used it. (This relies on S3 giving a copied
  object a fresh modification time, which I believe is right but have not verified.)

If the code is small enough to [inline](#where-the-code-is), none of this is needed: the code is in the template, and
the template is the whole release.
