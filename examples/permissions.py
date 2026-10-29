"""Sample IAM action sets for the examples. Copy and adjust them: they are not an API."""

# --8<-- [start:permissions]
SQS_CONSUME = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
DDB_WRITE = ["dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem"]
# --8<-- [end:permissions]
