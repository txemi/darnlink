"""A NUL in a path gives the same answer on every system (fila 35 of txnet1's schemas gate, frente 73b8a790).

`resolve()` raises on a NUL on Linux and takes it without raising on Windows with Python 3.13, so any code
that resolves before looking at the NUL answers differently on each: on Linux the three places below crashed
(`darnlink --robustify` on a `%00` link died with a traceback), and on Windows they gave a finding. darnlink
#20 fixed the same thing in `_probe` (292bbe6). Each test runs twice: as the system really behaves here, and
with `Path.resolve` swapped for one that does not raise, as on Windows with 3.13.
"""
import os
from pathlib import Path

import pytest

from darnlink.report import Kind
from darnlink.robustify import plan_robustify
from darnlink.yaml_refs import NO_SCHEMA, TypeRecognizer, _plan

U_A = "aaaaaaaa-1111-2222-3333-444444444444"


def _w(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


@pytest.fixture(params=["here", "resolve-does-not-raise"])
def system(request, monkeypatch):
    if request.param == "resolve-does-not-raise":
        monkeypatch.setattr(Path, "resolve", lambda self, strict=False: Path(os.path.normpath(os.path.abspath(self))))
    return request.param


def test_a_percent_00_markdown_link_is_dead_not_a_crash(tmp_path, system):
    doc = tmp_path / "doc.md"
    _w(doc, f"---\nuuid: {U_A}\n---\n\n[x](b%00c.md)\n")
    dead = [x for x in plan_robustify(tmp_path).findings if x.kind is Kind.DANGLING and x.file == doc]
    assert len(dead) == 1


def test_a_ref_with_a_nul_names_no_type(tmp_path, system):
    assert TypeRecognizer(tmp_path / "s.json")._names_the_types("x\0y.json") is False


def test_a_modeline_with_a_nul_is_an_unreadable_schema(tmp_path, system):
    _w(tmp_path / "data" / "card.yaml", "# yaml-language-server: $schema=../x\0y.json\nname: a\n")
    findings, _ = _plan(tmp_path, set())
    assert [f.kind for f in findings] == [NO_SCHEMA]


def test_a_literal_nul_in_a_markdown_link_is_dead_not_a_crash(tmp_path, system):
    # A NUL typed as is, not as `%00`: it reached `resolve()` through `resolved()` in `_anchor_target`, before any
    # of the guards above.
    doc = tmp_path / "doc.md"
    _w(doc, f"---\nuuid: {U_A}\n---\n\n[x](b\0c.md)\n")
    dead = [x for x in plan_robustify(tmp_path).findings if x.kind is Kind.DANGLING and x.file == doc]
    assert len(dead) == 1
