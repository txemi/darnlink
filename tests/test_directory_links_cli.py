"""Directory links judged through the CLI, the way a CI gate runs darnlink.

Regression guard for a platform difference seen on a Windows Jenkins agent: `darnlink check . --json`
reported every correct directory link (`[topic/](topic/) <!-- uuid: <README uuid> -->`) as needing a
repair (integrity FAIL), while the very same tree, at the same darnlink version, was clean on Linux.

The unit tests in test_directory_links.py call plan_repairs() directly. These go through main(), with
a relative root and a git repository, which is what a gate exercises. On failure they print, for
each directory link, the two paths repair compares, so a CI log is enough to diagnose the cause.
"""
import json
import subprocess

from gitenv import GIT_ENV as _GIT_ENV
import sys
from pathlib import Path

import pytest

from darnlink.cli import main
from darnlink.frontmatter_index import build_index
from darnlink.links import find_robust_links
from darnlink.paths import resolve_href

DIR_UUID = "210a2b81-cb63-4c26-b0f8-9fdf6ffb1d51"
TOP_UUID = "11111111-2222-3333-4444-555555555555"
OTHER_UUID = "66666666-7777-8888-9999-000000000000"


def _w(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _tree(root: Path) -> None:
    _w(root / "docs" / "guide" / "topic" / "README.md", f"---\nuuid: {DIR_UUID}\n---\n# Topic\n")
    _w(root / "docs" / "other" / "README.md", f"---\nuuid: {OTHER_UUID}\n---\n# Other\n")
    _w(root / "docs" / "guide" / "README.md",
       f"---\nuuid: {TOP_UUID}\n---\n# Guide\n\n"
       f"- [topic/](topic/) <!-- uuid: {DIR_UUID} -->\n"
       f"- [other](../other/) <!-- uuid: {OTHER_UUID} -->\n")
    subprocess.run(["git", "init", "-q", str(root)], check=True, env=_GIT_ENV)
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True, env=_GIT_ENV)


def _diagnose(root: Path) -> str:
    """For every directory link: the path the link resolves to and the directory its uuid names."""
    index = build_index(root)
    lines = []
    for f in sorted(root.rglob("*.md")):
        for link in find_robust_links(f.read_text(encoding="utf-8")):
            target = index.get(link.uuid)
            if target is None or link.href.strip().lower().endswith(".md"):
                continue
            current = resolve_href(link.href, f)
            intended = target.parent.resolve()
            lines.append(f"{f.relative_to(root)}: {link.href!r} current={current!r} "
                         f"intended={intended!r} equal={current == intended}")
    return "\n".join(lines)


def _check_json(capsys, root_arg: str):
    code = main(["check", root_arg, "--json"])
    return code, json.loads(capsys.readouterr().out)


def _assert_clean(code, payload, root: Path) -> None:
    repairs = payload["integrity"]["repairs"]
    assert not repairs and code == 0, (
        f"exit={code} repairs={repairs}\n{_diagnose(root)}\n"
        + json.dumps(payload["integrity"]["findings"], indent=1)[:3000])


def test_directory_links_are_clean_through_the_cli_with_a_relative_root(tmp_path, capsys, monkeypatch):
    _tree(tmp_path)
    monkeypatch.chdir(tmp_path)
    code, payload = _check_json(capsys, ".")
    _assert_clean(code, payload, tmp_path)


def test_directory_links_are_clean_through_the_cli_with_an_absolute_root(tmp_path, capsys):
    _tree(tmp_path)
    code, payload = _check_json(capsys, str(tmp_path))
    _assert_clean(code, payload, tmp_path)


@pytest.mark.skipif(sys.platform != "win32", reason="directory junctions are a Windows feature")
def test_directory_links_are_clean_when_the_tree_is_reached_through_a_junction(tmp_path, capsys, monkeypatch):
    """A CI workspace can sit under a folder that is a junction (a redirected user folder, say)."""
    real = tmp_path / "real"
    _tree(real)
    junction = tmp_path / "via_junction"
    subprocess.run(["cmd", "/c", "mklink", "/J", str(junction), str(real)], check=True,
                   capture_output=True)
    monkeypatch.chdir(junction)
    code, payload = _check_json(capsys, ".")
    _assert_clean(code, payload, junction)
