# Reviewing a change set before executing it

For a stack built with `cfn_typed.cli`, `python stacks.py plan NAME` does the first two steps below, prints the changes, and exits 1
when a table, bucket, queue, key, distribution or database would be replaced or removed (`--strict`: anything). `deployed` compares
the rendered template with the running one first. By hand:

```sh
aws cloudformation deploy --template-file template.json --stack-name NAME \
    --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM --no-execute-changeset
aws cloudformation describe-change-set --stack-name NAME --change-set-name <name printed above> \
    --query 'Changes[].ResourceChange.{Action:Action,Id:LogicalResourceId,Type:ResourceType,Replace:Replacement}' \
    --output table
```

Read it for: any `Remove` or `Replacement: True` on a stateful resource such as a table, bucket or queue (stop), and
any change you did not intend. Execute with
`aws cloudformation execute-change-set --stack-name NAME --change-set-name <name>` only after the user has seen it.
Delete an unwanted one with `aws cloudformation delete-change-set`.
