# Logical IDs the Serverless Framework generates

When importing from `sls package` output, keep these IDs: a changed ID is a replacement. The captured template is
authoritative; this list is what to expect in it. `Name` is the function key with its first letter upper-cased, `-`
written as `Dash` and `_` as `Underscore` (`my-fn` is `MyDashFn`).

| Resource | Logical ID | Stateful? |
|---|---|---|
| Deployment bucket | `ServerlessDeploymentBucket`, `ServerlessDeploymentBucketPolicy` | holds past artifacts; keep |
| Function | `{Name}LambdaFunction` | no |
| Log group | `{Name}LogGroup` | holds logs; set a retention, keep the ID |
| Version | `{Name}LambdaVersion{hash}` | the hash changes every deploy, so it never matches; expect a diff here |
| Execution role | `IamRoleLambdaExecution` | no |
| `schedule` event | `{Name}EventsRuleSchedule{n}`, `{Name}LambdaPermissionEventsRuleSchedule{n}` | no |
| `sqs` event | `{Name}EventSourceMappingSQS{QueueName}` | no (the queue itself is yours) |
| `http` events (REST API) | `ApiGatewayRestApi`, `ApiGatewayResource...`, `ApiGatewayMethod...`, `ApiGatewayDeployment{timestamp}`, `{Name}LambdaPermissionApiGateway` | the deployment ID changes every deploy |
| `httpApi` events | `HttpApi`, `HttpApiStage`, `HttpApiIntegration{Name}`, `HttpApiRoute...`, `{Name}LambdaPermissionHttpApi` | no |
| Resources under `resources:` in serverless.yml | the key you wrote | **yes, if tables, queues or buckets: Retain first** |

Resources whose ID contains a per-deploy hash or timestamp (`LambdaVersion`, `ApiGatewayDeployment`) will show as
changes in any change set. That is expected; everything else should not.
