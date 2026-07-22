"""Feature 011 — directory links.

A robust link may point at a *directory* instead of a `.md` file. The directory's stable identity
is the `uuid` of its `README.md`. The link's path names the directory (it does not end in `.md`);
the uuid comment carries the README's uuid.

- Robustify: a plain link to a directory with a `README.md` is anchored to that README's uuid.
- Repair: when the directory moves, the link's path is rewritten to the directory's new location
  (found via the README's uuid), kept as a directory path (trailing slash).
- Disambiguation is by the href shape alone (`.md` suffix -> file link; otherwise -> directory
  link), so it is deterministic and needs no disk access to classify.
"""
from pathlib import Path

import shutil

from darnlink.frontmatter_edit import read_uuid_from_content
from darnlink.frontmatter_index import build_index
from darnlink.links import find_robust_links
from darnlink.repair import apply_repairs, plan_repairs
from darnlink.robustify import apply_robustify, plan_robustify
from darnlink.report import Kind

DIR_UUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
OTHER_UUID = "11111111-2222-3333-4444-555555555555"


def _w(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


# --- Robustify ---------------------------------------------------------------------------------

def test_robustify_directory_link_reuses_readme_uuid(tmp_path):
    _w(tmp_path / "guide" / "README.md", f"---\nuuid: {DIR_UUID}\n---\n# Guide\n")
    _w(tmp_path / "A.md", "See the [guide](guide/) for details.\n")
    apply_robustify(plan_robustify(tmp_path))
    links = find_robust_links((tmp_path / "A.md").read_text())
    assert len(links) == 1
    assert links[0].href == "guide/"        # path unchanged (still a directory link)
    assert links[0].uuid == DIR_UUID        # anchored to the README's uuid


def test_robustify_directory_link_without_trailing_slash(tmp_path):
    _w(tmp_path / "guide" / "README.md", f"---\nuuid: {DIR_UUID}\n---\n# Guide\n")
    _w(tmp_path / "A.md", "See the [guide](guide) for details.\n")
    apply_robustify(plan_robustify(tmp_path))
    links = find_robust_links((tmp_path / "A.md").read_text())
    assert len(links) == 1
    assert links[0].href == "guide"         # path kept verbatim on robustify
    assert links[0].uuid == DIR_UUID


def test_robustify_directory_link_creates_uuid_in_readme_when_opted_in(tmp_path):
    _w(tmp_path / "guide" / "README.md", "# Guide (no frontmatter)\n")
    _w(tmp_path / "A.md", "See the [guide](guide/).\n")
    apply_robustify(plan_robustify(tmp_path, create_frontmatter=True))
    readme = (tmp_path / "guide" / "README.md").read_text()
    u = read_uuid_from_content(readme)
    assert u is not None
    assert find_robust_links((tmp_path / "A.md").read_text())[0].uuid == u


def test_robustify_directory_link_without_readme_is_left_plain(tmp_path):
    (tmp_path / "empty_dir").mkdir()
    _w(tmp_path / "A.md", "See the [dir](empty_dir/).\n")
    result = plan_robustify(tmp_path, create_frontmatter=True)
    assert result.new_content == {}         # a directory with no README is not anchorable


def test_robustify_directory_link_readme_no_uuid_reports_no_frontmatter(tmp_path):
    _w(tmp_path / "guide" / "README.md", "# Guide (no frontmatter)\n")
    _w(tmp_path / "A.md", "See the [guide](guide/).\n")
    result = plan_robustify(tmp_path, create_frontmatter=False)
    assert result.new_content == {}
    assert any(f.kind is Kind.NO_FRONTMATTER for f in result.findings)


def test_robustify_ignores_directory_named_like_an_md_file(tmp_path):
    # a *directory* whose name ends in `.md` must not be mistaken for an anchor file (it would fail
    # the later frontmatter read). Regression for the Copilot finding on _anchor_target.
    (tmp_path / "weird.md").mkdir()
    _w(tmp_path / "A.md", "[weird](weird.md)\n")
    result = plan_robustify(tmp_path, create_frontmatter=True)
    assert result.new_content == {}


# --- Repair ------------------------------------------------------------------------------------

def test_repair_directory_link_after_directory_moves(tmp_path):
    _w(tmp_path / "docs" / "guide" / "README.md", f"---\nuuid: {DIR_UUID}\n---\n# Guide\n")
    _w(tmp_path / "A.md", f"See the [guide](docs/guide/) <!-- uuid: {DIR_UUID} -->.\n")
    # move the directory
    shutil.move(str(tmp_path / "docs" / "guide"), str(tmp_path / "manuals_guide"))

    index = build_index(tmp_path)
    apply_repairs(plan_repairs(tmp_path, index))

    link = find_robust_links((tmp_path / "A.md").read_text())[0]
    assert link.href == "manuals_guide/"    # rewritten to the new dir, kept as a directory path
    assert link.uuid == DIR_UUID


def test_repair_directory_link_noop_when_already_correct(tmp_path):
    _w(tmp_path / "guide" / "README.md", f"---\nuuid: {DIR_UUID}\n---\n# Guide\n")
    _w(tmp_path / "A.md", f"[guide](guide/) <!-- uuid: {DIR_UUID} -->\n")
    index = build_index(tmp_path)
    result = plan_repairs(tmp_path, index)
    assert result.new_content == {}         # path already resolves to the README's directory


def test_repair_directory_link_noop_without_trailing_slash(tmp_path):
    # a correct directory link written WITHOUT a trailing slash must not churn
    _w(tmp_path / "guide" / "README.md", f"---\nuuid: {DIR_UUID}\n---\n# Guide\n")
    _w(tmp_path / "A.md", f"[guide](guide) <!-- uuid: {DIR_UUID} -->\n")
    index = build_index(tmp_path)
    result = plan_repairs(tmp_path, index)
    assert result.new_content == {}


def test_repair_directory_link_conflict_when_old_path_is_a_real_dir(tmp_path):
    # README moved, but a *different* real directory now sits at the old path: path and uuid
    # disagree -> conflict, leave untouched.
    _w(tmp_path / "new_home" / "README.md", f"---\nuuid: {DIR_UUID}\n---\n# Guide\n")
    (tmp_path / "guide").mkdir()            # an unrelated directory still exists at the old path
    _w(tmp_path / "A.md", f"[guide](guide/) <!-- uuid: {DIR_UUID} -->\n")
    index = build_index(tmp_path)
    result = plan_repairs(tmp_path, index)
    assert result.new_content == {}
    assert any(f.kind is Kind.CONFLICT for f in result.findings)


def test_repair_directory_link_conflict_when_old_path_is_a_real_file(tmp_path):
    # A non-`.md` link (classified as a directory link) whose path still resolves to a real FILE while
    # its uuid lives in a README elsewhere must NOT be hijacked — the path still resolves, so it is a
    # conflict, not a moved directory. (Regression for the Copilot finding on the defensive check.)
    _w(tmp_path / "new_home" / "README.md", f"---\nuuid: {DIR_UUID}\n---\n# Guide\n")
    _w(tmp_path / "LICENSE", "MIT\n")       # a real, non-.md file sits at the written path
    _w(tmp_path / "A.md", f"[license](LICENSE) <!-- uuid: {DIR_UUID} -->\n")
    index = build_index(tmp_path)
    result = plan_repairs(tmp_path, index)
    assert result.new_content == {}
    assert any(f.kind is Kind.CONFLICT for f in result.findings)


def test_repair_directory_link_conflict_when_uuid_is_not_a_readme(tmp_path):
    # a directory link whose uuid lives in a non-README file is malformed: flag, don't guess.
    _w(tmp_path / "notes.md", f"---\nuuid: {OTHER_UUID}\n---\n# Notes\n")
    _w(tmp_path / "A.md", f"[somewhere](somewhere/) <!-- uuid: {OTHER_UUID} -->\n")
    index = build_index(tmp_path)
    result = plan_repairs(tmp_path, index)
    assert result.new_content == {}
    assert any(f.kind is Kind.CONFLICT for f in result.findings)


# --- Regression: file links to a README.md still behave as file links --------------------------

def test_file_link_to_readme_still_points_to_the_file(tmp_path):
    _w(tmp_path / "docs" / "guide" / "README.md", f"---\nuuid: {DIR_UUID}\n---\n# Guide\n")
    _w(tmp_path / "A.md", f"[guide](docs/guide/README.md) <!-- uuid: {DIR_UUID} -->.\n")
    shutil.move(str(tmp_path / "docs" / "guide"), str(tmp_path / "manuals_guide"))

    index = build_index(tmp_path)
    apply_repairs(plan_repairs(tmp_path, index))

    link = find_robust_links((tmp_path / "A.md").read_text())[0]
    assert link.href == "manuals_guide/README.md"   # points at the FILE, not the directory
