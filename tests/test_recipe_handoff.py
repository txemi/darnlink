"""The installed recipe hands off to the one the repo PINS (`recipe_sha256` / `recipe_ps1_sha256`).

The recipe is installed once per machine, but each repo pins its own in `darnlink-gate.json`. When the
running copy's digest differs from the pinned one, it fetches the pinned recipe, verifies it, caches it
by digest and execs it. These tests never touch the network: `DARNLINK_GATE_RECIPE_BASE` is a
`file://` directory holding a tiny stub recipe that prints a marker and exits.

Where a test must show that NO hand-off happened, the gate goes on to its pre-flight, which runs `uvx`;
a `uvx` shim that exits 1 turns that into the fail-open "can't run darnlink" skip. Reaching that line
is the proof the run went past the hand-off as the installed copy.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from gitenv import GIT_ENV

ROOT = Path(__file__).resolve().parent.parent
RECIPE = ROOT / "recipes" / "darnlink-gate"
PS1_RECIPE = ROOT / "recipes" / "darnlink-gate.ps1"
WINDOWS = sys.platform.startswith("win") or os.name == "nt"
VER = "v9.9.9"
REF = f"git+https://example.invalid/darnlink@{VER}"

STUB = """#!/usr/bin/env bash
echo "PINNED-STUB-RAN args=$*"
echo "HANDOFF_DONE=${DARNLINK_GATE_HANDOFF_DONE:-}"
echo "PWD=$PWD"
echo "UMASK=$(umask)"
exit "${STUB_RC:-0}"
"""

STUB_PS1 = """Write-Output "PINNED-PS1-RAN args=$($args -join ' ')"
Write-Output "HANDOFF_DONE=$env:DARNLINK_GATE_HANDOFF_DONE"
exit 0
"""

# Any of these in the outer environment would steer the recipe under test.
_STEERING = ("DARNLINK_REF", "DARNLINK_GATE_MODE", "DARNLINK_GATE_SCOPE", "DARNLINK_GATE_FAIL_CLOSED",
             "DARNLINK_GATE_HANDOFF_DONE", "DARNLINK_GATE_RECIPE_BASE", "DARNLINK_GATE_CACHE",
             "DARNLINK_GATE_SYSTEM_CACHE", "DARNLINK_GATE_PS1_SHA256", "XDG_CACHE_HOME",
             "DARNLINK_GATE_REPORT")


def _sha(data: str | bytes) -> str:
    return hashlib.sha256(data.encode() if isinstance(data, str) else data).hexdigest()


def _cached_files(d: Path) -> list[str]:
    return sorted(p.name for p in d.iterdir()) if d.exists() else []


requires_bash = pytest.mark.skipif(
    WINDOWS or shutil.which("bash") is None or shutil.which("git") is None
    or shutil.which("curl") is None or shutil.which("python3") is None,
    reason="the bash hand-off needs a POSIX bash, git, curl and python3")


class Sandbox:
    def __init__(self, tmp_path: Path):
        self.tmp = tmp_path
        self.repo = tmp_path / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=self.repo, env=GIT_ENV, check=True)
        self.base = tmp_path / "base"
        self.cache = tmp_path / "cache"
        self.bindir = tmp_path / "bin"
        self.bindir.mkdir()
        uvx = self.bindir / "uvx"   # pre-flight fails -> fail-open skip: "ran as installed"
        uvx.write_text("#!/usr/bin/env bash\nexit 1\n")
        uvx.chmod(0o755)

    def serve(self, body: str, name: str = "darnlink-gate", ver: str = VER) -> str:
        d = self.base / ver / "recipes"
        d.mkdir(parents=True, exist_ok=True)
        (d / name).write_bytes(body.encode())
        return _sha(body)

    def env(self, **extra: str | None) -> dict:
        env = {k: v for k, v in GIT_ENV.items() if k not in _STEERING}
        env["PATH"] = f"{self.bindir}{os.pathsep}{env.get('PATH', '')}"
        env["DARNLINK_GATE_RECIPE_BASE"] = self.base.as_uri()
        env["DARNLINK_GATE_CACHE"] = str(self.cache)
        env["GIT_CEILING_DIRECTORIES"] = str(self.tmp)
        for k, v in extra.items():
            if v is None:
                env.pop(k, None)
            else:
                env[k] = v
        return env

    def run(self, config: dict, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
        (self.repo / "darnlink-gate.json").write_text(json.dumps(config))
        return subprocess.run(["bash", str(RECIPE), *args], cwd=self.repo, env=env or self.env(),
                              capture_output=True, text=True, timeout=120)


@pytest.fixture
def sb(tmp_path):
    return Sandbox(tmp_path)


# --- (a) equal digest, (h) loop guard: no hand-off ------------------------------------------------

@requires_bash
def test_a_matching_digest_runs_the_installed_recipe(sb):
    r = sb.run({"ref": REF, "recipe_sha256": _sha(RECIPE.read_bytes())})
    assert r.returncode == 0, r.stderr
    assert "handing off" not in r.stderr
    assert "can't run darnlink" in r.stderr, r.stderr   # went on, as itself
    assert _cached_files(sb.cache) == []


@requires_bash
def test_handoff_done_in_the_env_means_no_second_handoff(sb):
    sb.serve(STUB)
    r = sb.run({"ref": REF, "recipe_sha256": _sha(STUB)}, env=sb.env(DARNLINK_GATE_HANDOFF_DONE="1"))
    assert "PINNED-STUB-RAN" not in r.stdout
    assert "handing off" not in r.stderr
    assert "can't run darnlink" in r.stderr, r.stderr
    assert _cached_files(sb.cache) == []


@requires_bash
def test_without_the_key_nothing_is_fetched(sb):
    sb.serve(STUB)
    r = sb.run({"ref": REF})
    assert "PINNED-STUB-RAN" not in r.stdout and "handing off" not in r.stderr
    assert _cached_files(sb.cache) == []


# --- (b) hand-off, (c) cache, (g) uppercase -------------------------------------------------------

@requires_bash
def test_a_different_digest_hands_off_to_the_verified_pinned_recipe(sb):
    digest = sb.serve(STUB)
    r = sb.run({"ref": REF, "recipe_sha256": digest}, "one", "two")
    assert r.returncode == 0, r.stderr
    assert "PINNED-STUB-RAN args=one two" in r.stdout
    assert "HANDOFF_DONE=1" in r.stdout
    assert f"PWD={sb.repo}" in r.stdout
    assert "handing off" in r.stderr and VER in r.stderr and digest in r.stderr
    assert _cached_files(sb.cache) == [digest]                     # no temp file left beside it
    assert (sb.cache / digest).read_text() == STUB


@requires_bash
def test_the_pinned_recipe_exit_code_is_the_gate_exit_code(sb):
    digest = sb.serve(STUB)
    r = sb.run({"ref": REF, "recipe_sha256": digest}, env=sb.env(STUB_RC="3"))
    assert r.returncode == 3, r.stderr


@requires_bash
def test_the_second_run_uses_the_cache_without_the_network(sb):
    digest = sb.serve(STUB)
    assert sb.run({"ref": REF, "recipe_sha256": digest}).returncode == 0
    sb.base.rename(sb.tmp / "base-gone")                          # the "network" is gone
    r = sb.run({"ref": REF, "recipe_sha256": digest})
    assert r.returncode == 0, r.stderr
    assert "PINNED-STUB-RAN" in r.stdout


@requires_bash
def test_a_cached_file_that_changed_on_disk_is_fetched_again(sb):
    digest = sb.serve(STUB)
    sb.cache.mkdir(mode=0o700)
    (sb.cache / digest).write_text("#!/usr/bin/env bash\necho EVIL\n")
    (sb.cache / digest).chmod(0o600)
    r = sb.run({"ref": REF, "recipe_sha256": digest})
    assert r.returncode == 0, r.stderr
    assert "EVIL" not in r.stdout and "PINNED-STUB-RAN" in r.stdout
    assert (sb.cache / digest).read_text() == STUB


@requires_bash
def test_an_uppercase_digest_is_a_real_digest(sb):
    digest = sb.serve(STUB)
    r = sb.run({"ref": REF, "recipe_sha256": digest.upper()})
    assert r.returncode == 0, r.stderr
    assert "PINNED-STUB-RAN" in r.stdout


# --- (d) mismatch, (e) fetch fails, (f) malformed -------------------------------------------------

@requires_bash
@pytest.mark.parametrize("fail_closed", ["", "1"])
def test_a_mismatch_fails_with_1_names_the_mundane_cause_and_caches_nothing(sb, fail_closed):
    sb.serve(STUB)
    r = sb.run({"ref": REF, "recipe_sha256": _sha("the bytes someone sealed")},
               env=sb.env(DARNLINK_GATE_FAIL_CLOSED=fail_closed))
    assert r.returncode == 1, r.stderr
    assert "PINNED-STUB-RAN" not in r.stdout
    line = next(l for l in r.stderr.splitlines() if "checksum mismatch" in l)
    assert line.index("re-sealing") < line.index("tampered"), line
    assert _cached_files(sb.cache) == []                           # temp file removed too


@requires_bash
def test_a_fetch_that_fails_is_a_skip_when_fail_open(sb):
    sb.base.mkdir()                                                # nothing served
    r = sb.run({"ref": REF, "recipe_sha256": _sha(STUB)})
    assert r.returncode == 0, r.stderr
    assert "SKIP" in r.stderr
    url = f"{sb.base.as_uri()}/{VER}/recipes/darnlink-gate"
    line = next(l for l in r.stderr.splitlines() if "cannot fetch" in l)
    assert VER in line and url in line, line                       # the version AND the full URL
    assert _cached_files(sb.cache) == []


@requires_bash
def test_a_fetch_that_fails_is_a_4_when_fail_closed(sb):
    sb.base.mkdir()
    r = sb.run({"ref": REF, "recipe_sha256": _sha(STUB), "fail_closed": True})
    assert r.returncode == 4, r.stderr
    assert "FAILING" in r.stderr


@requires_bash
@pytest.mark.parametrize("bad", ["<64 hex chars>", "abc", "g" * 64, "a" * 63, "a" * 65])
def test_a_malformed_digest_is_a_config_error(sb, bad):
    sb.serve(STUB)
    r = sb.run({"ref": REF, "recipe_sha256": bad})
    assert r.returncode == 1, r.stderr
    assert "is not a sha256 digest" in r.stderr
    assert "PINNED-STUB-RAN" not in r.stdout


@requires_bash
@pytest.mark.parametrize("ref", [
    "git+https://example.invalid/darnlink",              # no @ at all
    "git+ssh://git@example.invalid/darnlink",            # the last @ is the host's user
    "git+https://example.invalid/darnlink@v1/../x",      # a path, not a version
    "git+https://example.invalid/darnlink@..",
    "git+https://example.invalid/darnlink@.",
    "git+https://example.invalid/darnlink@v1?x",
    "git+https://example.invalid/darnlink@v1#x",
    "git+https://example.invalid/darnlink@",
])
@pytest.mark.parametrize("fail_closed", ["", "1"])
def test_a_ref_without_a_clean_version_is_a_config_error(sb, ref, fail_closed):
    """The version becomes a URL path segment: anything but [A-Za-z0-9._+-]+ (and not . or ..) is
    refused before any fetch, with 1 on every surface, naming the ref."""
    sb.serve(STUB)
    r = sb.run({"ref": ref, "recipe_sha256": _sha(STUB)}, env=sb.env(DARNLINK_GATE_FAIL_CLOSED=fail_closed))
    assert r.returncode == 1, r.stderr
    assert f"ref='{ref}'" in r.stderr, r.stderr
    assert "PINNED-STUB-RAN" not in r.stdout
    assert _cached_files(sb.cache) == []


@requires_bash
@pytest.mark.parametrize("ver", ["v0.32.0", "0123abcdef", "v1.0.0+build_7-rc"])
def test_a_clean_version_is_accepted(sb, ver):
    digest = sb.serve(STUB, ver=ver)
    r = sb.run({"ref": f"git+https://example.invalid/darnlink@{ver}", "recipe_sha256": digest})
    assert r.returncode == 0, r.stderr
    assert "PINNED-STUB-RAN" in r.stdout


# --- the cache: only this uid can write it (the hash-then-exec window) --------------------------------

def _caller_umask() -> str:
    old = os.umask(0)
    os.umask(old)
    return f"{old:04o}"


@requires_bash
def test_what_the_handoff_creates_is_owner_only_and_the_umask_is_given_back(sb):
    digest = sb.serve(STUB)
    r = sb.run({"ref": REF, "recipe_sha256": digest})
    assert r.returncode == 0, r.stderr
    assert (sb.cache.stat().st_mode & 0o777) == 0o700
    assert (sb.cache / digest).stat().st_mode & 0o077 == 0
    assert f"UMASK={_caller_umask()}" in r.stdout                  # the pinned recipe gets the caller's


@requires_bash
@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="root owns everything")
@pytest.mark.parametrize("mode", [0o770, 0o707, 0o777])
@pytest.mark.parametrize("fail_closed, rc", [("", 0), ("1", 4)])
def test_a_cache_directory_others_can_write_is_refused(sb, mode, fail_closed, rc):
    digest = sb.serve(STUB)
    sb.cache.mkdir()
    sb.cache.chmod(mode)
    r = sb.run({"ref": REF, "recipe_sha256": digest}, env=sb.env(DARNLINK_GATE_FAIL_CLOSED=fail_closed))
    assert r.returncode == rc, r.stderr
    assert "not safe to run from" in r.stderr, r.stderr
    assert ("SKIP" in r.stderr) == (rc == 0)
    assert "PINNED-STUB-RAN" not in r.stdout
    assert _cached_files(sb.cache) == []


@requires_bash
@pytest.mark.parametrize("fail_closed, rc", [("", 0), ("1", 4)])
def test_a_symlinked_cache_directory_is_refused(sb, fail_closed, rc):
    digest = sb.serve(STUB)
    real = sb.tmp / "real-cache"
    real.mkdir(mode=0o700)
    sb.cache.symlink_to(real)
    r = sb.run({"ref": REF, "recipe_sha256": digest}, env=sb.env(DARNLINK_GATE_FAIL_CLOSED=fail_closed))
    assert r.returncode == rc, r.stderr
    assert "not safe to run from" in r.stderr and "PINNED-STUB-RAN" not in r.stdout
    assert _cached_files(real) == []


@requires_bash
@pytest.mark.parametrize("fail_closed, rc", [("", 0), ("1", 4)])
def test_a_symlink_planted_at_the_digest_is_never_executed(sb, fail_closed, rc):
    """The link points at a file with the RIGHT bytes, so only the symlink check can stop it: whoever
    owns the target could change it between the hash and the exec."""
    digest = sb.serve(STUB)
    target = sb.tmp / "elsewhere"
    target.write_text(STUB)
    sb.cache.mkdir(mode=0o700)
    (sb.cache / digest).symlink_to(target)
    r = sb.run({"ref": REF, "recipe_sha256": digest}, env=sb.env(DARNLINK_GATE_FAIL_CLOSED=fail_closed))
    assert r.returncode == rc, r.stderr
    assert "PINNED-STUB-RAN" not in r.stdout
    assert "not safe to run" in r.stderr and "symlink" in r.stderr
    assert (sb.cache / digest).is_symlink()                        # refused, not silently replaced


@requires_bash
@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="root owns everything")
def test_a_cached_file_others_can_write_is_refused(sb):
    digest = sb.serve(STUB)
    sb.cache.mkdir(mode=0o700)
    (sb.cache / digest).write_text(STUB)
    (sb.cache / digest).chmod(0o666)
    r = sb.run({"ref": REF, "recipe_sha256": digest}, env=sb.env(DARNLINK_GATE_FAIL_CLOSED="1"))
    assert r.returncode == 4, r.stderr
    assert "PINNED-STUB-RAN" not in r.stdout and "not safe to run" in r.stderr


# --- fail fast: bounded timeouts, no retry ----------------------------------------------------------

@requires_bash
def test_the_fetch_is_bounded_and_never_retried(sb):
    log = sb.tmp / "curl.argv"
    curl = sb.bindir / "curl"
    curl.write_text(f"#!/usr/bin/env bash\nprintf '%s\\n' \"$@\" > '{log}'\nexit 28\n")   # 28 = timeout
    curl.chmod(0o755)
    r = sb.run({"ref": REF, "recipe_sha256": _sha(STUB)}, env=sb.env(DARNLINK_GATE_FAIL_CLOSED="1"))
    assert r.returncode == 4, r.stderr
    argv = log.read_text().splitlines()
    assert argv[argv.index("--connect-timeout") + 1] == "10"
    assert argv[argv.index("--max-time") + 1] == "60"
    assert not any(a.startswith("--retry") for a in argv), argv


# --- where the cache lives: fixed, bounded, never /tmp ------------------------------------------------

def _env_without_explicit_cache(sb: Sandbox, **extra: str | None) -> dict:
    return sb.env(DARNLINK_GATE_CACHE=None, **extra)


@requires_bash
def test_an_explicit_cache_wins_over_the_agent_directory(sb):
    digest = sb.serve(STUB)
    system = sb.tmp / "var-cache"
    system.mkdir(mode=0o700)
    r = sb.run({"ref": REF, "recipe_sha256": digest},
               env=sb.env(DARNLINK_GATE_SYSTEM_CACHE=str(system)))
    assert r.returncode == 0, r.stderr
    assert _cached_files(sb.cache) == [digest] and _cached_files(system) == []


@requires_bash
def test_the_agent_directory_is_used_when_it_exists_and_is_writable(sb):
    digest = sb.serve(STUB)
    system = sb.tmp / "var-cache"
    system.mkdir(mode=0o700)
    r = sb.run({"ref": REF, "recipe_sha256": digest},
               env=_env_without_explicit_cache(sb, DARNLINK_GATE_SYSTEM_CACHE=str(system)))
    assert r.returncode == 0, r.stderr
    assert _cached_files(system) == [digest]


@requires_bash
@pytest.mark.skipif(not WINDOWS and hasattr(os, "geteuid") and os.geteuid() == 0,
                    reason="root can write a 0555 directory")
def test_an_agent_directory_that_is_not_writable_is_passed_over(sb):
    digest = sb.serve(STUB)
    system = sb.tmp / "var-cache"
    system.mkdir()
    system.chmod(0o555)
    try:
        r = sb.run({"ref": REF, "recipe_sha256": digest},
                   env=_env_without_explicit_cache(sb, DARNLINK_GATE_SYSTEM_CACHE=str(system),
                                                   XDG_CACHE_HOME=str(sb.tmp / "xdg"),
                                                   TMPDIR=tempfile.gettempdir(),
                                                   DARNLINK_GATE_FAIL_CLOSED="1"))
    finally:
        system.chmod(0o755)
    assert _cached_files(system) == []
    # The next candidate is XDG_CACHE_HOME, which here lives under the temp directory: refused.
    assert r.returncode == 4 and "under a temp directory" in r.stderr, r.stderr


@requires_bash
@pytest.mark.parametrize("fail_closed, rc", [("", 0), ("1", 4)])
def test_a_default_cache_under_a_temp_directory_is_refused(sb, fail_closed, rc):
    """pytest's tmp_path lives under the temp directory, so an XDG_CACHE_HOME in it is exactly the case."""
    digest = sb.serve(STUB)
    xdg = sb.tmp / "xdg"
    r = sb.run({"ref": REF, "recipe_sha256": digest},
               env=_env_without_explicit_cache(sb, DARNLINK_GATE_SYSTEM_CACHE=str(sb.tmp / "absent"),
                                               XDG_CACHE_HOME=str(xdg), TMPDIR=tempfile.gettempdir(),
                                               DARNLINK_GATE_FAIL_CLOSED=fail_closed))
    assert r.returncode == rc, r.stderr
    assert "under a temp directory" in r.stderr and "PINNED-STUB-RAN" not in r.stdout
    assert not xdg.exists()


@requires_bash
def test_a_home_with_a_temp_home_is_refused_too(sb):
    """A CI user whose HOME is /tmp: the case the rule exists for."""
    r = sb.run({"ref": REF, "recipe_sha256": _sha(STUB)},
               env=_env_without_explicit_cache(sb, DARNLINK_GATE_SYSTEM_CACHE=str(sb.tmp / "absent"),
                                               HOME="/tmp", DARNLINK_GATE_FAIL_CLOSED="1"))
    assert r.returncode == 4 and "/tmp/.cache/darnlink-gate" in r.stderr, r.stderr


@requires_bash
def test_no_cache_candidate_at_all_is_a_cant_gate(sb):
    r = sb.run({"ref": REF, "recipe_sha256": _sha(STUB)},
               env=_env_without_explicit_cache(sb, DARNLINK_GATE_SYSTEM_CACHE=str(sb.tmp / "absent"),
                                               HOME=None, DARNLINK_GATE_FAIL_CLOSED="1"))
    assert r.returncode == 4 and "no cache directory" in r.stderr, r.stderr


@pytest.fixture
def home_outside_tmp():
    """A HOME that is not under any temp directory, so the last rung of the cache order can be seen
    working. Made under the real ~/.cache (removed afterwards); skipped where that is itself temp."""
    parent = Path.home() / ".cache"
    tmp_root = os.path.realpath(tempfile.gettempdir())
    if not parent.is_dir() or os.path.realpath(parent).startswith((tmp_root, "/tmp")):
        pytest.skip("no ~/.cache outside the temp directory to stand in for a real HOME")
    d = Path(tempfile.mkdtemp(prefix="darnlink-handoff-test-", dir=parent))
    yield d
    shutil.rmtree(d, ignore_errors=True)


@requires_bash
def test_the_home_cache_is_the_last_rung(sb, home_outside_tmp):
    digest = sb.serve(STUB)
    r = sb.run({"ref": REF, "recipe_sha256": digest},
               env=_env_without_explicit_cache(sb, DARNLINK_GATE_SYSTEM_CACHE=str(sb.tmp / "absent"),
                                               HOME=str(home_outside_tmp)))
    assert r.returncode == 0, r.stderr
    assert _cached_files(home_outside_tmp / ".cache" / "darnlink-gate") == [digest]


# --- PowerShell: its own key, same behaviour ----------------------------------------------------------

def _powershell() -> str | None:
    return shutil.which("pwsh") or shutil.which("powershell")


requires_ps = pytest.mark.skipif(_powershell() is None or shutil.which("git") is None,
                                 reason="no pwsh or powershell on PATH: these run where CI has it")


def _run_ps(sb: Sandbox, config: dict, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    (sb.repo / "darnlink-gate.json").write_text(json.dumps(config))
    cmd = [_powershell(), "-NoProfile", "-NonInteractive"]
    if WINDOWS:
        cmd += ["-ExecutionPolicy", "Bypass"]
    return subprocess.run(cmd + ["-File", str(PS1_RECIPE), *args], cwd=sb.repo, env=env or sb.env(),
                          capture_output=True, text=True, timeout=300)


@requires_ps
def test_ps1_hands_off_on_its_own_digest(sb):
    digest = sb.serve(STUB_PS1, name="darnlink-gate.ps1")
    r = _run_ps(sb, {"ref": REF, "recipe_ps1_sha256": digest}, "one")
    assert r.returncode == 0, r.stderr
    assert "PINNED-PS1-RAN args=one" in r.stdout and "HANDOFF_DONE=1" in r.stdout
    assert _cached_files(sb.cache) == [f"{digest}.ps1"]


@requires_ps
def test_ps1_takes_its_digest_from_the_environment_too(sb):
    digest = sb.serve(STUB_PS1, name="darnlink-gate.ps1")
    r = _run_ps(sb, {"ref": REF}, env=sb.env(DARNLINK_GATE_PS1_SHA256=digest.upper()))
    assert r.returncode == 0, r.stderr
    assert "PINNED-PS1-RAN" in r.stdout


@requires_ps
def test_ps1_mismatch_is_1_and_caches_nothing(sb):
    sb.serve(STUB_PS1, name="darnlink-gate.ps1")
    r = _run_ps(sb, {"ref": REF, "recipe_ps1_sha256": _sha("sealed")})
    assert r.returncode == 1, r.stderr
    assert "checksum mismatch" in r.stderr and "PINNED-PS1-RAN" not in r.stdout
    assert _cached_files(sb.cache) == []


@requires_ps
@pytest.mark.parametrize("ver", ["v1/../x", "..", "v1?x"])
def test_ps1_a_ref_without_a_clean_version_is_1(sb, ver):
    r = _run_ps(sb, {"ref": f"git+https://example.invalid/darnlink@{ver}", "recipe_ps1_sha256": _sha(STUB_PS1)})
    assert r.returncode == 1 and "does not end in" in r.stderr, r.stderr


@requires_ps
def test_ps1_a_symlink_planted_at_the_digest_is_never_executed(sb):
    digest = sb.serve(STUB_PS1, name="darnlink-gate.ps1")
    target = sb.tmp / "elsewhere.ps1"
    target.write_text(STUB_PS1)
    sb.cache.mkdir(mode=0o700)
    try:
        (sb.cache / f"{digest}.ps1").symlink_to(target)
    except OSError:
        pytest.skip("this account cannot create symlinks")
    r = _run_ps(sb, {"ref": REF, "recipe_ps1_sha256": digest, "fail_closed": True})
    assert r.returncode == 4, r.stderr
    assert "PINNED-PS1-RAN" not in r.stdout and "not safe to run" in r.stderr


@requires_ps
def test_ps1_malformed_digest_is_1(sb):
    r = _run_ps(sb, {"ref": REF, "recipe_ps1_sha256": "abc"})
    assert r.returncode == 1 and "is not a sha256 digest" in r.stderr, r.stderr


@requires_ps
def test_ps1_fetch_failure_is_4_when_fail_closed_and_names_version_and_url(sb):
    sb.base.mkdir()
    r = _run_ps(sb, {"ref": REF, "recipe_ps1_sha256": _sha(STUB_PS1), "fail_closed": True})
    assert r.returncode == 4, r.stderr
    assert VER in r.stderr and "/recipes/darnlink-gate.ps1" in r.stderr


@requires_ps
@pytest.mark.skipif(WINDOWS, reason="the uvx shim is a POSIX script")
def test_ps1_never_hands_off_on_the_bash_digest_and_says_so(sb):
    """`recipe_sha256` is the digest of the BASH file: honouring it here would be a permanent mismatch."""
    sb.serve(STUB_PS1, name="darnlink-gate.ps1")
    r = _run_ps(sb, {"ref": REF, "recipe_sha256": _sha(STUB)})
    assert "PINNED-PS1-RAN" not in r.stdout and "checksum mismatch" not in r.stderr
    assert "recipe_ps1_sha256" in r.stderr, r.stderr
    assert _cached_files(sb.cache) == []
