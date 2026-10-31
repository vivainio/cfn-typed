# Distributing your patterns

Once you have helpers worth sharing (a load balancer fragment, an organisation's defaults),
you will want them in a package other repositories can install. The question is what to do
about the generated types the helpers are built with.

## The recommendation

**Generate the types your package uses at build time, into a private module, and ship them
in the wheel. Do not commit them.**

```text
corp-patterns/
  cfn-typegen.toml           # out = "src/corp/_types", types = [...] the patterns use
  pyproject.toml
  src/corp/
    __init__.py
    network.py               # your patterns
    _types/                  # generated at build time, gitignored, shipped in the wheel
```

and one rule that keeps the boundary clean:

!!! note "The rule"
    **Public signatures use only `cfn_typed` types** (`Expr`, `Tag`, `Resources`,
    `AnyResource`, `Params`) and builtins. Generated types appear only inside function
    bodies.

```python
from corp._types import sqs                      # private, generated

def queue_with_dlq(name: str, *, tags: list[Expr[Tag]] | None = None) -> Resources:
    ...                                          # builds with sqs.queue(...) inside
```

!!! note "The sumo exception"
    `cfn-typed-sumo`, built from this repository, ships its generated types as a public module
    (`cfn_typed_sumo.types`) so that users can build their own resources with the same types the
    patterns use. The private-types advice below is for small pattern packages.

## Why this shape

- **Callers install and use it.** Nothing to generate before calling `queue_with_dlq`.
- **Your own code is still checked.** Inside the package, a misspelled property is a type
  error, which is where mistakes are easiest to introduce.
- **No clash with the caller's types.** TypedDicts are structural, so your private
  `sqs.Queue` and a caller's own generated `sqs.Queue` are different classes that the type
  checker treats as interchangeable `AnyResource` values. The caller generates only what
  *their* templates use.
- **Small.** The wheel carries only the resources your patterns need, and `docs = false`
  trims the descriptions.
- **The repository stays free of generated code.** It is produced by the build, like any
  other artefact.

The alternatives are worse. If the patterns import the *caller's* generated module, they
depend on a module name and location they do not control. If they use no generated types at
all, nothing checks the dictionaries they build. Shipping every resource type costs about
6 MB per release for types nobody uses.

## Build setup

**Gitignore the directory**, and **tell the build to include it anyway**:

```toml
# pyproject.toml
[tool.hatch.build]
artifacts = ["src/corp/_types"]
```

!!! warning "Put `artifacts` under `[tool.hatch.build]`"
    Hatch leaves out gitignored files, so without this setting the wheel silently has no
    types. Setting it only under `[tool.hatch.build.targets.wheel]` is not enough: plain
    `uv build` builds the sdist first and then builds the wheel *from that sdist*, so the
    wheel still comes out without the types. Under `[tool.hatch.build]` the setting applies
    to both. This was checked by building a throwaway package each way.

**Generate before building.** In the release workflow, the step before `uv build`:

```yaml
- run: uv run cfn-typegen        # reads cfn-typegen.toml
- run: uv build
```

**Generate in development too**, so `ty` and the tests can see the types. A one-line
`conftest.py` does it for tests, as in this repository; or run the same command by hand.

## Using it

```sh
uv add corp-patterns            # brings cfn-typed with it
```

The caller's templates need no generated types to use your helpers. They generate only the
resource types they use directly, with `cfn-typegen`.

## Trade-offs

- **Types are frozen at release time.** A property AWS adds next week reaches your users in
  your next release. That is usually what you want, and it makes builds reproducible.
- **Different days, different snapshots.** The schema zip is not pinned, so two releases built
  on different days can differ slightly. Every generated file records which snapshot it came
  from in its header, for example:

    ```python
    # Schema snapshot: sha256:3f9c1a0b7d2e
    ```

    To rebuild an old release identically, keep that release's `CloudformationSchema.zip`
    (a release asset works) and pass it with `--schemas`.
- **A refresh is explicit.** `cfn-typegen --refresh` downloads the schemas again; otherwise
  the cached copy in `~/.cache/cfn-typegen/` is used. See [the generator](generator.md).
