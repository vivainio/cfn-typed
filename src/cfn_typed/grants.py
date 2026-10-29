"""Opinion layer: the AWS CDK's permission sets. Less permanent than the generated types and the names.

    from cfn_typed import grants

    grants.Sqs.Queue.consume_messages.on(queue_arn)          # statements, as the CDK's grantConsumeMessages
    grants.S3.Bucket.read.on(bucket_arn, key_arn=my_key)     # bucket and objects, plus the KMS read

Which actions belong together, and on which resources, is a judgement, not a fact. These sets are the AWS CDK's
judgement (https://github.com/aws/aws-cdk, Apache-2.0, credited in NOTICE), copied at a pinned commit for the major
services. They are not AWS guidance and not a statement of what is right for you.

Treat this module as **unstable**: unlike the generated resource types and `cfn_typed.permissions`, which are
facts, a set can change when the CDK's opinion changes, may be renamed or removed in any release, and may move to a
separate package. Pin the version of cfn-typed that you use, or copy the sets you rely on into your own code.
The `.on(...)` statements carry no `Principal`; put them in a role, a managed policy or any policy document.
"""

from cfn_typed._cdk_grants import *  # noqa: F403 - the generated service classes (see __all__ there)
from cfn_typed._cdk_grants import __all__ as _services
from cfn_typed._grant import Grant, Shape

__all__ = ["Grant", "Shape", *_services]
