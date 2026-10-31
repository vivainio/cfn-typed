# Data flows

Change streams, uploads and delivery, after the Solutions Constructs `dynamodb-stream-lambda`, `s3-lambda` and
`kinesisfirehose-s3` patterns. Each connects a source of records to a destination, and each has one wiring detail
that is easy to get wrong.

```python
--8<-- "packages/sumo/src/cfn_typed_sumo/integrations.py:imports"
```

## A table stream into a Lambda

```python
--8<-- "packages/sumo/src/cfn_typed_sumo/integrations.py:stream_trigger"
```

```python
table = with_stream(dynamodb_table("pk"))          # the table, now with a stream
trigger = stream_trigger("Changes", "Processor", "Orders")
role = lambda_role("processor", trigger.statements)
```

- **The handle carries the statements.** The function's role needs stream read permissions, and the mapping alone
  does not give them. `trigger.statements` goes straight into [`lambda_role`](lambda-role.md).
- **A failing batch is retried until the record expires** (24 hours for a stream) and blocks the shard behind it. The
  pattern bounds retries and splits a failing batch in two (`BisectBatchOnFunctionError`) to find the bad record.
- **`with_stream` returns a new table.** The table from [`dynamodb_table`](storage.md) is not changed.

## A bucket that invokes a Lambda

```python
--8<-- "packages/sumo/src/cfn_typed_sumo/integrations.py:bucket_to_lambda"
```

This is the classic circular dependency, and the reason CDK has to work around it. The bucket's notification names
the function, and S3 checks at creation that it may invoke it, so the **permission has to exist first**. A
permission that gives the bucket as `SourceArn: !GetAtt Bucket.Arn` would make the bucket wait for itself.
The way out is a fixed bucket name:

- the permission builds the ARN from the name, so it does not refer to the bucket,
- the bucket has `DependsOn` the permission,
- and `SourceAccount` stops any other account's bucket of the same name from invoking the function.

The cost is that a bucket with a fixed name cannot be replaced while it exists. If that matters,
turn on EventBridge notifications for the bucket and use [`event_to_lambda`](messaging.md) instead.

## Firehose into a bucket

```python
--8<-- "packages/sumo/src/cfn_typed_sumo/integrations.py:firehose_to_s3"
```

- **Two S3 statements, not one.** `ListBucket` applies to the bucket and `PutObject` to its objects, so a
  single statement over both is wrong for one of them. The IAM check says so.
- **The trust policy has an `ExternalId`.** It is the account id, so only Firehose acting for this account can
  assume the role.
- **The log stream is created by the pattern.** Firehose writes to a stream that already exists, and does not
  create one, so without it delivery errors would be silent. The delivery stream waits for it.
- **Compressed and buffered.** GZIP files of at most five minutes or 64 MB, so the bucket gets few large objects and
  not many tiny ones.
