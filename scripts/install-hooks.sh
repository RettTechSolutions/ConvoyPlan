#!/bin/sh
# Install local Git hooks from .hooks/ into .git/hooks/
set -e

REPO_ROOT=$(git rev-parse --show-toplevel)
HOOKS_DIR="$REPO_ROOT/.hooks"
GIT_HOOKS_DIR="$REPO_ROOT/.git/hooks"

for hook in "$HOOKS_DIR"/*; do
    name=$(basename "$hook")
    target="$GIT_HOOKS_DIR/$name"
    ln -sf "$REPO_ROOT/.hooks/$name" "$target"
    echo "Installed: .git/hooks/$name -> .hooks/$name"
done

echo "Done. Hooks active."
