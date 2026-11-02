#!/bin/zsh
set -eu
# Resolve this newly created project's own directory, including spaces.
# -B disables Python bytecode cache files. Nothing is installed or saved.
exec /usr/bin/python3 -B "${0:A:h}/menu.py"
