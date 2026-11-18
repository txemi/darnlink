"""The repository carries no symlink, because it is also a Jenkins pipeline library.

A Jenkinsfile loads this repository as a library to call `darnlinkGate()` (`vars/darnlinkGate.groovy`), and Jenkins
refuses a library that contains a symlink anywhere in it: the build ends with "Rejecting library: symlink found:
AGENTS.md" before any stage runs. Measured on txnet1_nginx#8 (18-nov-2026), when `AGENTS.md` and
`.github/copilot-instructions.md` were symlinks to `CLAUDE.md`. They are short pointer files now. This test fails on the
next symlink before it reaches a release, because the version a consumer loads is a release tag.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from gitenv import GIT_ENV

ROOT = Path(__file__).resolve().parents[1]


def test_no_tracked_file_is_a_symlink():
    out = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-s"], capture_output=True, text=True, check=True,
                         env=GIT_ENV).stdout
    links = [line.split("\t", 1)[1] for line in out.splitlines() if line.startswith("120000 ")]
    assert not links, f"symlinks in the repository (Jenkins rejects the library): {links}"
