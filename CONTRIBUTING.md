# Contributing

## Adding an IAM service to the permission names

`cfn_typed.permissions` has the exact IAM actions of a short list of major services. If you need another service,
open a pull request. It is a one-line change:

1. Add the service to `SERVICES` in `scripts/sync-permissions.py`: the IAM prefix and the class name, for example
   `"ecr": "Ecr"`. The prefix is the part before the colon in an action (`ecr:BatchGetImage`).
2. Regenerate the module. `uv run` installs awacs just for the script; it is not a dependency of cfn-typed:

   ```sh
   uv run scripts/sync-permissions.py
   ```

3. Check it, and commit the regenerated `src/cfn_typed/permissions.py` with the script change:

   ```sh
   uv run ty check
   uv run pytest
   ```

That is all. The tests derive everything from the module, so there is nothing else to update, and the book's reference
page is generated.

The script stops with a clear message if awacs has no such prefix, or if an action cannot become a Python name.

Adding a service adds its **names** only. The [grants](https://vivainio.github.io/cfn-typed/grants/) are copied from
the AWS CDK by `scripts/sync-cdk-grants.py`, so a service gets grants only if the CDK has them, and that is a separate
change.

## Everything else

Facts, such as the generated types and the permission names, and opinions, such as grants and patterns, are kept
apart on purpose (see the book's landing page). A change that adds an opinion should say so and be placed in a
layer that is marked as one.
