# Reviewing a change set before executing it

```sh
aws cloudformation deploy --template-file template.json --stack-name NAME \
    --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM --no-execute-changeset
aws cloudformation describe-change-set --stack-name NAME --change-set-name <name printed above> \
    --query 'Changes[].ResourceChange.{Action:Action,Id:LogicalResourceId,Type:ResourceType,Replace:Replacement}' \
    --output table
```

Read it for: any `Remove` or `Replacement: True` on a stateful resource (stop), and anything that is not the
per-deploy noise listed in [serverless-ids.md](serverless-ids.md). Execute with
`aws cloudformation execute-change-set --stack-name NAME --change-set-name <name>` only after the user has seen it.
Delete an unwanted one with `aws cloudformation delete-change-set`.
