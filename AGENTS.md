# Instructions for coding agents

This repository's conventions for any coding agent live in one file: **`CLAUDE.md`**, at the repository root. Read it before
changing anything.

This file is a pointer, not a copy, so the conventions exist once and cannot drift. It used to be a symlink to `CLAUDE.md`,
but the repository is also a Jenkins pipeline library (`vars/darnlinkGate.groovy`), and Jenkins rejects any library that
contains a symlink ("Rejecting library: symlink found"). `tests/test_no_symlinks.py` keeps it that way.
