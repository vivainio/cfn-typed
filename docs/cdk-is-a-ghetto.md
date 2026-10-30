---
icon: lucide/skull
---

# CDK is a Ghetto

![Node.js brain damage](https://github.com/user-attachments/assets/d9bf3d11-4d30-44b2-ac4f-9133daa7f3ee){ width="720" }

You wanted a Lambda function and a queue. Maybe some tags. You got 10 million lines of Node dot JS.

## Just use Python

"Hey, I don't need to use Node, I will just use Python." So here is your Python. Open the CDK's own
Python `Bucket` (`aws_cdk/aws_s3/__init__.py` in the
[`aws-cdk-lib`](https://pypi.org/project/aws-cdk-lib/) package) and the whole implementation is this:

```python
jsii.create(self.__class__, self, [scope, id, props])
```

It does nothing. It sends a line of JSON down a pipe to a Node.js process that holds the real bucket,
started with a heap limit of 4.069 GB (`--max-old-space-size=4069`), because Node obviously needs
4.069 GB to generate your 6 lines of JSON. Lucky you got a 64 bit OS now. It is not even JSON-RPC. It is a bespoke RPC protocol, to
call a TypeScript library from Python.

The wheel is 59 MB and installs as 219 MB. It's Node.js and 2000 npm deps in a
trenchcoat. Now you can add tests with Jest! That is just another 3000 dependencies, to check for odd
and even numbers.

## Refactoring destroys your resources

You refactor by moving one line. You tidy the database into a nicer parent construct, and the CDK
destroys your database to start a new one. You may have lost all your customers, but you get a cleaner
TypeScript file.

The fix is open heart surgery with the [`cdk refactor`](https://docs.aws.amazon.com/cdk/v2/guide/ref-cli-cmd-refactor.html) command (preview), in a terminal with production AWS access
that operations personnel have to log into for you, while your customers are breathing down your neck.

## `cdk synth` is for show

In theory you read the template before you deploy it. In practice nobody can read what comes out, and
half of it you never asked for. So the last real check is `cdk deploy` against your precious production
account, where you find out what the template says by running it.

Synthesizing the stack takes 200 ms, as opposed to a 5 minute deploy where you hope for the best.

## You can't trust the ecosystem

The big selling point is the ecosystem: a construct for everything, published by someone. But your
CloudFormation stacks are your crown jewels. They decide how well production behaves. You would not
hand that to a 24 year old barista with a college AWS account, and a third-party construct is exactly
that: IAM, networking and removal policies decided by code you did not write and will not read, pulled
in with one `npm install`.
In practice you skip even that: you copy a bunch of .ts files from an adjacent team that got a semi-neat
solution working.

## Before the first deploy, you deploy a stack

Every account and region has to be *bootstrapped* first: a stack of roles and buckets that exist so
you can deploy a template that might have been forty lines.

## What the CDK is good at

Honesty, briefly. If you want high-level constructs, bundled assets, a large ecosystem and bindings in
several languages, the CDK has them. Because you got a sudden urge to use the Java SDK to generate those 6
lines of JSON.

A [more balanced take](comparison.md).

Historical inspiration from 2008: Zed Shaw's
[Rails is a Ghetto](https://web.archive.org/web/20080107/http://www.zedshaw.com/rants/rails_is_a_ghetto.html)
(archived copy; he took the original down after the internet had a field day with it).
