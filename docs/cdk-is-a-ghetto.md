---
icon: lucide/skull
---

# CDK is a ghetto

You wanted a Lambda function and a queue. You got a program.

## You thought you could just use Python

Here is how the CDK gives you Python. The library is written in TypeScript. A tool called jsii compiles
it to JavaScript and generates a Python class for every class in it. Open one of those classes and the
body of `Bucket.__init__` ends with this:

```python
jsii.create(self.__class__, self, [scope, id, props])
```

That is the whole implementation. The Python `Bucket` does nothing: it sends a message to a Node.js
process that holds the real one. The `jsii` package starts `node` with `subprocess.Popen` and a heap
limit of 4.069 GB (`--max-old-space-size=4069`), because Node obviously needs 4.069 GB to accomplish the
JSON generation. Then it writes one line of JSON to the child's stdin for each call, and reads one line
of JSON back from its stdout. Your objects
live in the other process, and Python keeps a reference to each. When the CDK calls a method you
overrode, the call goes back down the pipe the other way. It is not even JSON-RPC: it is a bespoke RPC
protocol, to call a TypeScript library from Python.

The `aws-cdk-lib` 2.273.0 wheel is 59 MB, and installs as roughly 219 MB. Most of that is Python proxy
files, one of them 16 MB (`aws_quicksight`), plus a 37 MB archive containing the real library: 3123
JavaScript files. You thought you could just use Python, but it's Node.js and 2000 npm deps in a
trenchcoat.

Here it is Python, and the output is `json.dumps`.

## Your template is the output of a program

With the CDK the thing you review is not the thing that deploys. You write TypeScript, or Python that
talks to a Node.js process through jsii, the code builds a tree of constructs, and `cdk synth` flattens
the tree into a CloudFormation template that nobody wrote and few people read. When the two disagree,
you debug the program by reading its output.

Here the template is a `dict`. You can `print` it. There is nothing in between.

## `cdk synth` is for show

In theory you run `cdk synth`, read the template and deploy it when you are happy. In practice nobody
can review what comes out. Logical IDs carry a hash (`MyBucketF68F3FF0`), assets turn into parameters
and keys, and the CDK adds its own metadata, bootstrap version checks and helper resources that
you never asked for. Even synthesis is not always offline: a lookup such as `Vpc.fromLookup` asks your
AWS account what is in it, and the answer is cached in `cdk.context.json`. So the last real check
is `cdk deploy` against your precious production account, and you find out what the template says by
running it.

Here the template you read is the template you deploy, and generating it asks nobody anything. The stack
gets 200 ms to synthesize, as opposed to a 5 minute deploy where you hope for the best.

## Refactoring destroys your resources

You refactor by moving one line. You tidy the database into a nicer parent construct, and the CDK
destroys your database to start a new one. You may have lost all your customers, but you get a cleaner
TypeScript file.

The cause is that the CDK derives each resource's logical ID from its path in the construct tree, plus
a hash. Move the construct and the path changes, and the logical ID with it. To CloudFormation a
changed logical ID is a deletion and a creation, and it does not ask what is in the old one. The escape
hatch is to override the logical ID by hand, after you have found out.

Here a logical ID is a key in a dict. It is whatever you typed, and it moves only when you move it.

## The same code can mean different permissions

`queue.grantConsumeMessages(role)` decides which actions to grant, adds the key permissions if the queue
is encrypted, and **mutates the role you passed in**. Some of what it decides depends on feature flags:
the S3 grants, for example, behave differently under `S3_GRANT_WRITE_WITHOUT_ACL`. Two apps can run
identical code and end up with different IAM. That is a defensible way to improve defaults without
breaking anyone, and a poor way to answer the question "what can this role do?".

Here a [grant](grants.md) returns statements. You choose where they go, and you can read them.

## You can't trust the ecosystem

The big selling point is the ecosystem: a construct for everything, published by someone. But your
CloudFormation stacks are your crown jewels. They decide how well production behaves, who can read
your data and what happens when something is renamed. You would not hand that to a 24 year old
barista with a college AWS account, and a third-party construct is exactly that: IAM, networking and
removal policies decided by code you did not write and will not read, pulled in with one `npm install`.

Here the patterns are [examples to copy](patterns/index.md), not packages to depend on. Copy one into
your repo and it is yours, in plain dicts, where you can read every line.

## Before the first deploy, you deploy a stack

The CDK needs each account and region to be *bootstrapped*: a stack that creates roles, a staging
bucket and a repository for assets. It is a reasonable design for bundling assets. It is also a
prerequisite you have to explain to every new account, for a template that might have been forty lines.

Here nothing is installed in your account. Deploy the template with whatever client you like.

## What you get instead

| | CDK | cfn-typed |
|---|---|---|
| You write | a program that builds a construct tree | a `dict` |
| You review | the program, then the synthesized template | the template |
| Logical IDs | derived from the tree | the keys you wrote |
| Permissions | decided by the construct, sometimes by a flag | returned as statements |
| Needs | the CDK, Node.js (via jsii for Python), a bootstrapped account | `json.dumps` |
| Types | in the language of your choice | in `ty`, from AWS's own schemas |

The types are not given up. `cfn-typegen` reads the same CloudFormation resource schemas that the CDK's
L1 constructs are generated from, so a typo or a missing required property is an error in your editor
before anything runs.

## What the CDK is good at

Honesty, briefly. If you want high-level constructs, bundled and published assets, a large ecosystem,
and bindings in several languages, the CDK has them and cfn-typed does not, and it has no plans to.
Some of the CDK's best ideas are worth keeping: the [L2 patterns page](patterns/cdk-l2.md) shows how
to write them as plain functions that return plain dicts.

A [more balanced take](comparison.md).

Read the historical inspiration: Zed Shaw's
[Rails is a Ghetto](https://web.archive.org/web/20080107/http://www.zedshaw.com/rants/rails_is_a_ghetto.html)
(archived copy; he later took the original down).
