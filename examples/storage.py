"""Encrypted storage patterns shown in the book (docs/patterns/storage.md and publishing.md)."""

# --8<-- [start:imports]
import re
from collections.abc import Mapping, Sequence

from cfn_types import dynamodb, ecr, kms, s3, ssm

from cfn_typed import Expr, Resources, Tag, allow, deny, get_att, join, ref, sub
from cfn_typed.dynamodb import Index, Key, keys
from cfn_typed.permissions import Ecr
from cfn_typed.policy import ANY, GlobalKeys, aws, bool_, string_not_like

# --8<-- [end:imports]


# --8<-- [start:encryption_key]
def encryption_key(name: str, *, alias: str, description: str = "", tags: list[Expr[Tag]] | None = None) -> Resources:
    """A KMS key with rotation and an alias: logical IDs `{name}Key` and `{name}KeyAlias`.

    The key policy only enables IAM: access is then granted with ordinary identity policies. Both resources
    are retained when the stack is deleted, because deleting a key makes everything encrypted with it unreadable.
    """
    key = f"{name}Key"
    props: kms.KeyProps = {
        "Description": description or f"{name} encryption key",
        "EnableKeyRotation": True,
        "KeyPolicy": {
            "Version": "2012-10-17",
            "Statement": [
                # in a key policy Resource "*" means the key itself; naming its ARN would be a circular reference
                allow("kms:*", "*", sid="EnableIamPolicies", principal=aws(sub("arn:${AWS::Partition}:iam::${AWS::AccountId}:root"))),
            ],
        },
    }
    if tags:
        props["Tags"] = tags
    return {
        key: kms.key(deletion_policy="Retain", update_replace_policy="Retain", **props),
        f"{name}KeyAlias": kms.alias(
            AliasName=f"alias/{alias}", TargetKeyId=ref(key), deletion_policy="Retain", update_replace_policy="Retain",
        ),
    }
# --8<-- [end:encryption_key]


# --8<-- [start:secure_bucket]
def secure_bucket(
    name: str,
    *,
    key_arn: Expr[str],
    allowed_principals: Sequence[Expr[str]] | None = None,
    archive_after_days: int | None = None,
    tags: list[Expr[Tag]] | None = None,
) -> Resources:
    """A private, encrypted bucket and its policy: logical IDs `{name}Bucket` and `{name}BucketPolicy`.

    Public access is blocked, objects are encrypted with `key_arn`, and the bucket is retained on delete. The
    policy refuses plain HTTP. With `allowed_principals` it also refuses everyone else, so include the role that
    deploys the stack, or you will lock yourself out of the bucket.
    """
    bucket = f"{name}Bucket"
    bucket_arn = get_att(bucket, "Arn")
    both: list[Expr[str]] = [bucket_arn, join("", [bucket_arn, "/*"])]
    statements = [
        deny("s3:*", both, sid="DenyInsecureTransport", principal=ANY, condition=bool_(GlobalKeys.SecureTransport, False)),
    ]
    if allowed_principals:
        statements.append(
            deny("s3:*", both, sid="DenyEveryoneElse", principal=ANY,
                 condition=string_not_like(GlobalKeys.PrincipalArn, list(allowed_principals))),
        )
    props: s3.BucketProps = {
        "PublicAccessBlockConfiguration": {
            "BlockPublicAcls": True, "BlockPublicPolicy": True, "IgnorePublicAcls": True, "RestrictPublicBuckets": True,
        },
        "BucketEncryption": {"ServerSideEncryptionConfiguration": [{
            "ServerSideEncryptionByDefault": {"SSEAlgorithm": "aws:kms", "KMSMasterKeyID": key_arn},
            "BucketKeyEnabled": True,
        }]},
    }
    if archive_after_days is not None:
        props["LifecycleConfiguration"] = {"Rules": [{
            "Id": "archive", "Status": "Enabled",
            "Transitions": [{"StorageClass": "GLACIER", "TransitionInDays": archive_after_days}],
        }]}
    if tags:
        props["Tags"] = tags
    return {
        bucket: s3.bucket(deletion_policy="Retain", update_replace_policy="Retain", **props),
        f"{name}BucketPolicy": s3.bucket_policy(
            Bucket=ref(bucket), PolicyDocument={"Version": "2012-10-17", "Statement": statements},
        ),
    }
# --8<-- [end:secure_bucket]


# --8<-- [start:dynamodb_table]
def dynamodb_table(
    pk: Key,
    sk: Key | None = None,
    *,
    gsis: Sequence[Index] = (),
    lsis: Sequence[Index] = (),
    deletion_protection: bool = True,
    tags: list[Expr[Tag]] | None = None,
) -> dynamodb.Table:
    """An on-demand table with point-in-time recovery. Keys are `"name"` (a string) or `("name", "N")`."""
    return dynamodb.table(
        **keys(pk, sk, gsis=gsis, lsis=lsis),
        BillingMode="PAY_PER_REQUEST",
        PointInTimeRecoverySpecification={"PointInTimeRecoveryEnabled": True},
        DeletionProtectionEnabled=deletion_protection,
        **({"Tags": tags} if tags else {}),
    )
# --8<-- [end:dynamodb_table]


# --8<-- [start:ecr_repository]
def ecr_repository(
    name: str,
    *,
    pull_principals: Sequence[Expr[str]] = (),
    tags: list[Expr[Tag]] | None = None,
) -> ecr.Repository:
    """A repository with immutable tags and scan-on-push, that the given principals may pull from."""
    props: ecr.RepositoryProps = {
        "RepositoryName": name,
        "ImageTagMutability": "IMMUTABLE",
        "ImageScanningConfiguration": {"ScanOnPush": True},
    }
    if pull_principals:
        props["RepositoryPolicyText"] = {
            "Version": "2012-10-17",
            "Statement": [
                # no Resource: a repository policy applies to the repository it is attached to
                allow([Ecr.GetDownloadUrlForLayer, Ecr.BatchGetImage, Ecr.BatchCheckLayerAvailability],
                      sid="AllowPull", principal=aws(*pull_principals)),
            ],
        }
    if tags:
        props["Tags"] = tags
    return ecr.repository(**props)
# --8<-- [end:ecr_repository]


# --8<-- [start:publish]
def publish(prefix: str, values: Mapping[str, Expr[str]]) -> Resources:
    """Publish values as SSM parameters named `{prefix}/{key}`, for other stacks to read.

    `publish("/data/storage", {"key-arn": get_att("DataKey", "Arn")})` creates the logical ID `KeyArnParameter`.
    """
    return {
        "".join(part.capitalize() for part in re.split(r"[^A-Za-z0-9]+", key)) + "Parameter": ssm.parameter(
            Type="String", Name=f"{prefix}/{key}", Value=value,
        )
        for key, value in values.items()
    }
# --8<-- [end:publish]
