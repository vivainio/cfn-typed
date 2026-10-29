#!/bin/sh
# Generate the types the examples use and the reference pages, then build the book.
set -eu
cd "$(dirname "$0")/.."
cfn-typegen --out examples/cfn_types $(grep -v '^#' examples/types.txt)
python docs/gen_reference.py
zensical build --clean
