#!/bin/sh
# Generate the types the examples use and the reference pages, then build the book.
set -eu
cd "$(dirname "$0")/.."
cfn-typegen --config examples/cfn-typegen.toml
cfn-typegen --config packages/sumo/cfn-typegen.toml
python docs/gen_reference.py
zensical build --clean
cp agent-quickstart.md site/agent-quickstart.md # the raw markdown page, served next to the book
