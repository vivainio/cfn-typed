---
icon: lucide/skull
---

# CDK is a ghetto

You wanted a Lambda function and a queue. You got a program.

## You thought you could just use Python

Open the Python `Bucket` and the whole implementation is this:

```python
jsii.create(self.__class__, self, [scope, id, props])
```

It does nothing. It sends a line of JSON down a pipe to a Node.js process that holds the real bucket,
started with a heap limit of 4.069 GB (`--max-old-space-size=4069`), because Node obviously needs
4.069 GB to accomplish the JSON generation. It is not even JSON-RPC. It is a bespoke RPC protocol, to
call a TypeScript library from Python.

The wheel is 59 MB and installs as 219 MB. You thought you could just use Python, but it's Node.js and
2000 npm deps in a trenchcoat.

Here it is Python, and the output is `json.dumps`.

## Refactoring destroys your resources

You refactor by moving one line. You tidy the database into a nicer parent construct, and the CDK
destroys your database to start a new one. You may have lost all your customers, but you get a cleaner
TypeScript file.

The fix is open heart surgery with the [`cdk refactor`](https://docs.aws.amazon.com/cdk/v2/guide/ref-cli-cmd-refactor.html) command (preview), in a terminal with production AWS access
that operations personnel have to log into for you, while your customers are breathing down your neck.

Here a logical ID is a key in a dict. It moves only when you move it.

## `cdk synth` is for show

In theory you read the template before you deploy it. In practice nobody can read what comes out, and
half of it you never asked for. So the last real check is `cdk deploy` against your precious production
account, where you find out what the template says by running it.

Here the stack gets 200 ms to synthesize, as opposed to a 5 minute deploy where you hope for the best.

## Your template is the output of a program

The thing you review is not the thing that deploys. When the two disagree, you debug the program by
reading its output, which nobody wrote and few people read.

Here the template is a `dict`. You can `print` it.

## The same code can mean different permissions

Two apps can run identical code and get different IAM, depending on a feature flag. "What can this role
do?" is a question you answer by deploying it.

Here a [grant](grants.md) returns statements. You can read them.

## You can't trust the ecosystem

The big selling point is the ecosystem: a construct for everything, published by someone. But your
CloudFormation stacks are your crown jewels. They decide how well production behaves. You would not
hand that to a 24 year old barista with a college AWS account, and a third-party construct is exactly
that: IAM, networking and removal policies decided by code you did not write and will not read, pulled
in with one `npm install`.

Here the [patterns](patterns/index.md) are examples to copy, not packages to depend on.

## Before the first deploy, you deploy a stack

Every account and region has to be *bootstrapped* first: a stack of roles and buckets that exist so
you can deploy a template that might have been forty lines.

Here nothing is installed in your account.

## What the CDK is good at

Honesty, briefly. If you want high-level constructs, bundled assets, a large ecosystem and bindings in
several languages, the CDK has them and cfn-typed does not.

A [more balanced take](comparison.md).

Read the historical inspiration: Zed Shaw's
[Rails is a Ghetto](https://web.archive.org/web/20080107/http://www.zedshaw.com/rants/rails_is_a_ghetto.html)
(archived copy; he later took the original down).
