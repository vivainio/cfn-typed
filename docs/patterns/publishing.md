# Publishing values through SSM

A stack that owns shared resources has to tell other stacks where they are: a bucket's ARN, a key's ARN.
CloudFormation has *exports* for that, but an export cannot be changed or removed while another stack imports
it, which welds the two stacks together. **SSM parameters** are the looser alternative: the owner publishes
values under a path, and consumers read that path.

## The producer

`publish` turns a mapping into SSM parameters:

```python
--8<-- "packages/sumo/src/cfn_typed_sumo/storage.py:publish"
```

The whole producer stack, using the [storage patterns](storage.md):

```python
--8<-- "examples/data_platform.py:producer"
```

See the [rendered YAML](https://github.com/vivainio/cfn-typed/blob/main/examples/rendered/data-platform.yaml) or [in the book](../rendered/data-platform.md).

## The consumer

The consumer declares the same paths as [parameters](parameters.md). CloudFormation looks the values up when
the consumer deploys, so nothing about the producer appears in the consumer's source except two paths:

```python
--8<-- "examples/data_consumer.py:consumer"
```

`key_arn` and `bucket_arn` are ordinary `Ref`s. The [grant](../grants.md) builds the bucket-and-objects statement
from the bucket ARN and adds the key statement from the key ARN, so the role is allowed to read the bucket and decrypt
what is in it. [The rendered YAML](../rendered/data-consumer.md) shows the result.

## Things to know

- **The producer deploys first.** A parameter of an SSM type needs the SSM parameter to exist when the consumer is
  created or updated.
- **A consumer picks up a changed value on its next deploy**, not immediately. That is usually what you want:
  nothing changes underneath a running stack.
- **The paths are the contract.** Put them in one module, as `PREFIX` is here, and import it from both sides, or keep
  them in a shared defaults package, so a typo cannot make a consumer look at a path nobody publishes. The tests for
  this example check that everything the consumer reads, the producer publishes.
- **Publish ARNs, not names.** A consumer that needs an ARN should not have to rebuild it from a name, and a bucket
  without a fixed name has none to rebuild from.
