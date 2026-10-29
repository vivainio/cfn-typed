# Comparison

How cfn-typed relates to the tools you may be weighing it against: [Troposphere](https://github.com/cloudtools/troposphere)
(the closest), the [AWS CDK](https://github.com/aws/aws-cdk) and [Pulumi](https://www.pulumi.com/). It is meant to be
fair, so it says what each does better, and every claim here was checked (see [how this was checked](#how-this-was-checked)).

## The short version

cfn-typed is **a typing layer for CloudFormation templates, not a deployment tool**. You write Python that builds a
template, and any tool you like deploys it. It tries to keep **facts** primary (the shapes AWS publishes, the names of
IAM actions) and to fence **opinions** into modules and pages that are marked as such. The others make different
trade-offs, most of them on purpose.

| | cfn-typed | Troposphere | AWS CDK | Pulumi |
|---|---|---|---|---|
| What it is | generator + plain-dict builders | library of generated Python classes | framework with layered constructs | deployment engine with providers |
| Output | a CloudFormation template | a CloudFormation template | a CloudFormation template | none: it deploys directly |
| Who deploys | CloudFormation (any client) | CloudFormation (any client) | CloudFormation, via `cdk deploy` | Pulumi, with its own state |
| Language | Python 3.14+ | Python | TypeScript; Python, Java, .NET and Go through jsii | TypeScript, JavaScript, Python, Go, .NET, Java, YAML, HCL |
| Mistakes caught | **before running**, by the type checker | when the code runs | when the code runs | when the code runs |
| Runtime validation | none | yes | yes | yes |
| Opinions | in marked layers, kept apart | none in the core | built into L2 and L3 constructs | in the engine and in higher-level packages |

## Troposphere

The nearest neighbour: Python, CloudFormation in and out, generated resource classes. The difference is **when and how
mistakes are caught**. Here are the same three mistakes on the same Lambda function, as tested:

| Mistake | cfn-typed | Troposphere 4.11.0 |
|---|---|---|
| misspelled property (`MemorySise=256`) | `ty`: `unknown-argument` | `AttributeError` when the object is created. `ty`: nothing |
| wrong type (`Timeout="soon"`) | `ty`: `invalid-argument-type`, expected `Expr[int]` | `ValueError` when the object is created. `ty`: nothing |
| missing required property (`Code`) | `ty`: `missing-argument` | `ValueError` when the template is **rendered**. `ty`: nothing |

- **Static versus runtime.** Troposphere declares properties in a runtime `props` dictionary on each class and ships no
  `py.typed` or stubs, so a type checker has no property names to check. Its own check runs when the code runs, which
  means CI and synthesis rather than the editor. cfn-typed is the other way around: the editor and `ty` catch it, and
  at runtime the values are plain dicts that nothing validates. A value from `json.load` is not checked.
- **Objects and dicts.** Troposphere resources are objects registered with a `Template`. cfn-typed resources are
  plain dicts, so there is nothing to learn about the object model, and a fragment is just a dict you can merge.
- **Coverage.** Troposphere 4.11.0 has 330 generated service modules. cfn-typed generates the resource types you ask
  for, from the CloudFormation registry schemas.
- **YAML.** Both write short-form intrinsics. Troposphere sorts keys alphabetically; cfn-typed keeps insertion order,
  and writes IAM statements in the order IAM documents them.
- **IAM.** Troposphere's sibling library [awacs](https://github.com/cloudtools/awacs) (installed with
  `troposphere[policy]`) is **broader than cfn-typed's**: it ships `py.typed`, has 469 service modules of action names,
  and builds policies and conditions, and a misspelled action is an attribute error in a type checker. cfn-typed's
  [permission names](permissions.md) cover only the 11 services the AWS CDK uses, on purpose, and its
  [policy helpers](policy.md) are smaller. If you need complete IAM action names today, awacs has them.

Choose Troposphere if you want mature, widely used, runtime-validated Python classes for CloudFormation and are happy
with checks that happen when the code runs. Choose cfn-typed if you want mistakes in the editor, plain data, and
[committed, reviewable output](testing.md).

## AWS CDK

The CDK is a framework that provisions through CloudFormation. Its constructs come in layers: L1 are auto-generated
CloudFormation wrappers, L2 are intent-based APIs with smart defaults, and L3 are multi-resource patterns. It is
written in TypeScript, with Python, Java, .NET and Go bindings generated through jsii, and a deployment needs the
account and region to be *bootstrapped*, which creates roles and a staging bucket and repository for assets.

- **What the CDK has that cfn-typed does not:** the L2 and L3 constructs themselves, asset bundling and publishing, a large
  ecosystem, and bindings in several languages. cfn-typed has no construct tree and deploys nothing.
- **Where the line between fact and opinion falls.** L1 is facts. L2 mixes them: a `Bucket` carries defaults, and
  `queue.grantConsumeMessages(role)` decides which actions to grant, adds the key permissions if the queue is
  encrypted, and changes the role. Those decisions can move: in the CDK's S3 grants, which put actions you get depends on a
  feature flag (`S3_GRANT_WRITE_WITHOUT_ACL`), so the same code can mean different permissions in different apps.
  That is a reasonable way to ship improved defaults without breaking anyone, and it is the opposite of what cfn-typed
  tries to do. Here the [grants](grants.md) are *copied from the CDK, credited, and marked as an opinion layer* that
  is less permanent than the generated types.
- **Mutation.** A CDK grant modifies the grantee as a side effect. A cfn-typed grant returns statements, and you decide
  where they go, so everything stays plain data.

Choose the CDK for high-level constructs, asset handling and a large community. Choose cfn-typed if you want the
template to be the thing you reason about, without a framework deciding things in between.

## Pulumi

Pulumi is not a CloudFormation tool but an alternative to CloudFormation: it deploys through its own engine and
keeps its own state in a backend, and supports TypeScript, JavaScript, Python, Go, .NET, Java, YAML and HCL.

- **Providers.** For AWS it offers the Classic provider, built on the AWS Terraform provider, and the Cloud Control
  provider, generated from the AWS Cloud Control API. Pulumi's documentation says the latter derives resources from the
  CloudFormation resource schemas, the same family of data `cfn-typegen` reads, so the shapes agree. The difference is
  what happens next: Pulumi deploys them itself.
- **Where the line falls.** The engine, not CloudFormation, decides how a change is applied, so behaviour lives in the tool.
  With cfn-typed, CloudFormation stays the engine, and what the template says is what is deployed.
- **What Pulumi has that cfn-typed does not:** deployment, state, other clouds and SaaS providers, and many languages.

Choose Pulumi if you want one engine and model across clouds and languages, or your own state. Choose cfn-typed if you
are committed to CloudFormation and want better types and plain-data templates on top of it.

## What cfn-typed does not do

- It does not deploy, bundle assets, or hold state. CloudFormation and your usual client do that.
- It has no high-level constructs. The [patterns](patterns/index.md) are examples to copy.
- It does not validate at runtime. Types are checked by your type checker, so `cfn-lint` still belongs in CI.
- It is young, and Python 3.14 or later only. It has been tested with `ty`, not with other type checkers.
- Its permission names are limited to the services the CDK uses; [awacs](#troposphere) is more complete.

## Using it with the others

The output is a plain template, so nothing stops the pieces from combining. The [golden-file
check](testing.md) takes any mapping, and the YAML renderer takes any plain template dict, whichever tool built it.

## How this was checked

Written on 2026-10-29. The Troposphere and awacs rows come from installing `troposphere` 4.11.0 and `awacs` 2.6.0 and
running the mistakes above, with `ty` and at runtime. The CDK statements come from its repository (the construct
levels, the bootstrap resources, the S3 grants code, and the descriptions in its `grants.json` files at the commit named in
[grants](grants.md)). The Pulumi statements come from Pulumi's documentation. Tools change, so check the versions that matter to you.
