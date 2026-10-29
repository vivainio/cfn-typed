"""Sample IAM action sets for the examples, built from the permission names. Copy and adjust them."""

# --8<-- [start:permissions]
from cfn_typed.permissions import DynamoDb, Sqs

SQS_CONSUME = [Sqs.ReceiveMessage, Sqs.DeleteMessage, Sqs.GetQueueAttributes]
DDB_WRITE = [DynamoDb.PutItem, DynamoDb.UpdateItem, DynamoDb.DeleteItem]
# --8<-- [end:permissions]
