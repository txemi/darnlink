"""Feature 012 — `--create-readme`.

Opt-in extension of directory links (feature 011): a plain link to a directory that has **no**
`README.md` cannot be anchored, because a folder has no frontmatter of its own. With
`create_readme=True` (CLI `--create-readme`, which implies `--create-frontmatter`), darnlink creates
that `README.md` — with a fresh uuid and a `# <dirname>` heading — and anchors the link to it.

Boundary: darnlink creates a README **inside an existing directory only**; it never creates the
directory itself. Off by default, so the base guarantee ("never creates files") holds unless asked.
"""
from pathlib import Path

from darnlink.frontmatter_edit import read_uuid_from_content
from darnlink.frontmatter_index import build_index
from darnlink.links import find_robust_links
from darnlink.repair import apply_repairs, plan_repairs
from darnlink.report import Kind
from darnlink.robustify import apply_robustify, plan_robustify

EXISTING = "11111111-2222-3333-4444-555555555555"


def _w(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_create_readme_anchors_a_folder_without_one(tmp_path):
    (tmp_path / "hub").mkdir()
    _w(tmp_path / "A.md", "See the [hub](hub/).\n")
    result = plan_robustify(tmp_path, create_readme=True)
    apply_robustify(result)

    readme = tmp_path / "hub" / "README.md"
    assert readme.is_file()                                  # created
    u = read_uuid_from_content(readme.read_text())
    assert u is not None
    assert "# hub" in readme.read_text()                     # heading = directory name
    link = find_robust_links((tmp_path / "A.md").read_text())[0]
    assert link.href == "hub/"                               # still a directory link
    assert link.uuid == u                                    # anchored to the new README's uuid
    assert any(f.kind is Kind.CREATE_README for f in result.findings)


def test_create_readme_is_dry_run_by_default(tmp_path):
    (tmp_path / "hub").mkdir()
    _w(tmp_path / "A.md", "[hub](hub/)\n")
    result = plan_robustify(tmp_path, create_readme=True)   # planned, not applied
    assert (tmp_path / "hub" / "README.md") in result.new_content
    assert not (tmp_path / "hub" / "README.md").exists()    # nothing written without apply


def test_without_create_readme_folder_is_left_plain(tmp_path):
    # regression: default behaviour (feature 011) is unchanged — no README, link stays plain
    (tmp_path / "hub").mkdir()
    _w(tmp_path / "A.md", "[hub](hub/)\n")
    result = plan_robustify(tmp_path, create_frontmatter=True)  # but NOT create_readme
    assert result.new_content == {}
    assert not (tmp_path / "hub" / "README.md").exists()


def test_create_readme_one_readme_for_many_links_to_the_same_dir(tmp_path):
    (tmp_path / "hub").mkdir()
    _w(tmp_path / "A.md", "[hub](hub/) and again [hub](hub/).\n")
    _w(tmp_path / "B.md", "[hub](hub/) from B.\n")
    result = plan_robustify(tmp_path, create_readme=True)
    apply_robustify(result)
    creates = [f for f in result.findings if f.kind is Kind.CREATE_README]
    assert len(creates) == 1                                 # exactly one README, shared
    u = read_uuid_from_content((tmp_path / "hub" / "README.md").read_text())
    for name in ("A.md", "B.md"):
        for link in find_robust_links((tmp_path / name).read_text()):
            assert link.uuid == u


def test_create_readme_does_not_create_the_directory(tmp_path):
    # a link to a path that is not an existing directory: darnlink creates a README INSIDE an
    # existing folder only, never the folder — the link is left plain.
    _w(tmp_path / "A.md", "[ghost](ghost/)\n")
    result = plan_robustify(tmp_path, create_readme=True)
    assert result.new_content == {}
    assert not (tmp_path / "ghost").exists()


def test_create_readme_uses_existing_readme_when_present(tmp_path):
    _w(tmp_path / "hub" / "README.md", f"---\nuuid: {EXISTING}\n---\n# Hub\n")
    _w(tmp_path / "A.md", "[hub](hub/)\n")
    result = plan_robustify(tmp_path, create_readme=True)
    apply_robustify(result)
    assert not any(f.kind is Kind.CREATE_README for f in result.findings)   # nothing created
    assert find_robust_links((tmp_path / "A.md").read_text())[0].uuid == EXISTING
    # the existing README is untouched
    assert (tmp_path / "hub" / "README.md").read_text() == f"---\nuuid: {EXISTING}\n---\n# Hub\n"


def test_create_readme_implies_create_frontmatter_for_existing_readme(tmp_path):
    # FR-012f: --create-readme implies --create-frontmatter — at the API level, not just the CLI. A
    # directory whose README exists but has NO frontmatter gets a uuid without the caller also passing
    # create_frontmatter=True.
    _w(tmp_path / "hub" / "README.md", "# Hub (no frontmatter)\n")
    _w(tmp_path / "A.md", "[hub](hub/)\n")
    result = plan_robustify(tmp_path, create_readme=True)   # create_frontmatter NOT passed
    apply_robustify(result)
    u = read_uuid_from_content((tmp_path / "hub" / "README.md").read_text())
    assert u is not None                                    # uuid added to the existing README
    assert find_robust_links((tmp_path / "A.md").read_text())[0].uuid == u


def test_create_readme_respects_deny_list(tmp_path):
    (tmp_path / "hub").mkdir()
    _w(tmp_path / "A.md", "[hub](hub/)\n")
    result = plan_robustify(tmp_path, create_readme=True, no_create_globs=("README.md",))
    assert result.new_content == {}
    assert not (tmp_path / "hub" / "README.md").exists()


def test_create_readme_ignores_a_directory_named_readme(tmp_path):
    # pathological: `hub/README.md` exists but is itself a DIRECTORY. It must not be treated as
    # "missing" (scheduling a write there would crash at apply time). Left plain, no write planned.
    (tmp_path / "hub" / "README.md").mkdir(parents=True)
    _w(tmp_path / "A.md", "[hub](hub/)\n")
    result = plan_robustify(tmp_path, create_readme=True)
    assert result.new_content == {}


def test_create_readme_skips_excluded_directories(tmp_path):
    # a link from an INCLUDED file to a directory inside an --exclude'd subtree (e.g. a mirror, a
    # vendored clone) must not get a README created there — --create-readme respects --exclude for the
    # write target, not only for the scan.
    (tmp_path / "mirror" / "capture").mkdir(parents=True)
    _w(tmp_path / "A.md", "[cap](mirror/capture/)\n")
    result = plan_robustify(tmp_path, create_readme=True, excludes={"mirror"})
    assert result.new_content == {}
    assert not (tmp_path / "mirror" / "capture" / "README.md").exists()


def test_create_readme_never_writes_outside_the_scanned_root(tmp_path):
    # a `../`-escaping link must never make darnlink create a README outside the tree it was pointed at
    (tmp_path / "sub").mkdir()
    (tmp_path / "sibling").mkdir()              # a real directory OUTSIDE the scanned root
    _w(tmp_path / "sub" / "A.md", "[sib](../sibling/)\n")
    result = plan_robustify(tmp_path / "sub", create_readme=True)
    assert result.new_content == {}
    assert not (tmp_path / "sibling" / "README.md").exists()


def test_create_readme_never_writes_into_an_excluded_subtree(tmp_path):
    # a link from an INCLUDED file to a directory INSIDE an --exclude'd subtree (e.g. a mirror) must
    # not get a README created there — --exclude prunes the scan, and creation must respect it too.
    (tmp_path / "mirror" / "captured_chat").mkdir(parents=True)
    _w(tmp_path / "A.md", "[chat](mirror/captured_chat/)\n")
    result = plan_robustify(tmp_path, create_readme=True, excludes={"mirror"})
    assert result.new_content == {}
    assert not (tmp_path / "mirror" / "captured_chat" / "README.md").exists()


def test_created_readme_link_heals_after_move(tmp_path):
    (tmp_path / "docs" / "hub").mkdir(parents=True)
    _w(tmp_path / "A.md", "[hub](docs/hub/)\n")
    apply_robustify(plan_robustify(tmp_path, create_readme=True))
    import shutil
    shutil.move(str(tmp_path / "docs" / "hub"), str(tmp_path / "elsewhere"))
    index = build_index(tmp_path)
    apply_repairs(plan_repairs(tmp_path, index))
    assert find_robust_links((tmp_path / "A.md").read_text())[0].href == "elsewhere/"
