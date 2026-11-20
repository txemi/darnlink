// Jenkins shared-library step `darnlinkGate()` -- darnlink link gate, the SERVER-SIDE wall (piece 4).
//
// The ONE copy of the fetch-verify-run shell for Jenkins. Before it, every adopter's Jenkinsfile
// carried its own copy of these lines, and copies drift. A Jenkinsfile now writes:
//
//     @Library('darnlink') _
//     ...
//     stage('darnlink gate (links)') { steps { darnlinkGate() } }
//
// SETUP (once, on the Jenkins controller): declare this repository as a global pipeline library
// named `darnlink` (Manage Jenkins > System > Global Trusted Pipeline Libraries, or `globalLibraries`
// in Configuration as Code), with a default version. The library's version only decides THIS
// fetcher: the darnlink version that runs is the `ref` of the repo's own darnlink-gate.json, read at
// run time, so there is no second pin to keep in step.
// Make that default version a TAG, not a branch: it decides which copy of this verifier runs, and a
// branch is a mutable ref.
//
// WITHOUT the library: copy the shell of gateShell() below into an `sh` step of your declarative Jenkinsfile
// (recipes/examples/Jenkinsfile-stage.groovy shows where). It fetches the PINNED recipe from the
// PUBLIC darnlink repo -- no credentials -- and runs it FAIL-CLOSED.
//
// AGENTS: Linux and macOS run the shell with `sh`. A Windows agent runs the SAME shell with the bash of
//          Git for Windows (`bat`), so there is still one copy and one seal (`recipe_sha256`): see
//          windowsBash() below. It needs Git for Windows; DARNLINK_GATE_BASH names its bash.exe when it
//          is not under %ProgramFiles%/Git. It runs the bash recipe, not the .ps1 twin.
// ASSUMES: `uvx` is available on the agent. `astral-sh` installs `uv` into ~/.local/bin; if it isn't
//          on PATH, prepend it (e.g. `export PATH="$HOME/.local/bin:$PATH"`) inside the sh block.
// The pin is DERIVED from darnlink-gate.json, never repeated here. Two copies of a version number is
// one copy too many: the example this came from carried its own tag and it went stale, because
// nothing fails when two copies drift. Bump `darnlink-gate.json` and both CI surfaces move with it.

// REPORT: the step also keeps the gate's `darnlink check --json` document as the build artifact
// `darnlink-check.json`, so a fleet report can read each repo's counts (broken links, un-anchored,
// dangling) from its last build instead of parsing the console. Kept on a red build too: that is the
// build whose counts matter. Only a recipe from darnlink 0.32.0 on writes it; an older pin leaves no
// artifact, and the reader says "not measured" rather than zero.
def call() {
  withEnv(['DARNLINK_GATE_FAIL_CLOSED=1',   // the wall must fail closed
           "DARNLINK_GATE_REPORT=${env.WORKSPACE}/darnlink-check.json"]) {
    try {
      if (isUnix()) {
        sh gateShell()
      } else {
        windowsBash(gateShell())
      }
    } finally {
      archiveArtifacts artifacts: 'darnlink-check.json', allowEmptyArchive: true, fingerprint: false
    }
  }
}

// The fetch-verify-run shell, ONE copy for every agent family: call() hands it to `sh` on Linux and
// macOS and to windowsBash() on Windows. The tests extract this block and run it.
def gateShell() {
  return '''
      set -eu
      # A Windows agent hands WORKSPACE as a drive-letter path; Git bash names the same directory as
      # /c/..., the form every tool below accepts. The working directory IS the workspace.
      case "$(uname -s)" in MINGW* | MSYS* | CYGWIN* ) WORKSPACE=$PWD ;; esac
      # python3 is a hard dependency of the recipe (it parses darnlink-gate.json). A Windows agent often
      # has only `python` (or a `python3` that is the Store stub and runs nothing): then a temporary
      # python3 that runs python, on PATH for this step only. No Python 3 at all fails here, loudly:
      # without it the recipe would run an old darnlink with every default.
      ALIAS=
      trap '[ -z "$ALIAS" ] || rm -rf "$ALIAS"' EXIT
      is_python3() { "$1" -c 'import sys; sys.exit(sys.version_info[0] != 3)' >/dev/null 2>&1; }
      if ! is_python3 python3; then
        if is_python3 python; then
          ALIAS=$(mktemp -d)
          echo '#!/usr/bin/env bash' > "$ALIAS/python3"
          echo 'exec python "$@"' >> "$ALIAS/python3"
          chmod +x "$ALIAS/python3"
          PATH="$ALIAS:$PATH"
          export PATH
          echo "no working python3 on this agent: python runs as python3 for this step"
        else
          echo "no Python 3 on this agent (neither python3 nor python): the recipe cannot read darnlink-gate.json" >&2
          exit 1
        fi
      fi
      # A reused workspace keeps the last build's file: without this, a build that fails before the
      # check would archive the PREVIOUS build's counts as its own.
      if [ -n "${DARNLINK_GATE_REPORT:-}" ]; then rm -f "$DARNLINK_GATE_REPORT"; fi
      # Read the `ref` KEY, not the file — byte-identical to the GitHub Actions example on purpose.
      # A grep for a version-shaped string takes the first match anywhere in the json, so an excluded
      # path containing one would win silently: the same "silently picks a version" failure this step
      # exists to prevent. Any ref the recipe accepts works: tag, branch or SHA. python3 is already a
      # hard dependency of the recipe itself (it parses this same file).
      VER=$(python3 -c 'import json;print(json.load(open("darnlink-gate.json"))["ref"].rsplit("@",1)[1])') \
        || { echo "cannot derive the pin: darnlink-gate.json has no ref key, or its ref has no @version" >&2; exit 1; }
      # -f: fail on a 404 (moved/typo'd tag) instead of writing "404: Not Found" and running garbage.
      curl -fsSL "https://raw.githubusercontent.com/txemi/darnlink/$VER/recipes/darnlink-gate" \
        -o "$WORKSPACE/.darnlink-gate"
      # ⚠️ VERIFY BEFORE `chmod +x` -- byte-identical in intent to the GitHub Actions example, and for
      # the same reason: this fetches a script over the network and runs it. `recipe_sha256` is the
      # only statement about the BYTES; the pin is a mutable pointer (and may be a branch or a SHA).
      # ⚠️ NO BACKSLASH IN THIS BLOCK EXCEPT A LINE CONTINUATION (a backslash immediately before a
      # newline, as on the curl above -- Groovy and the shell both just remove it, so they agree).
      # That rule is load-bearing twice over. Groovy processes
      # escape sequences inside a triple-quoted string, so a backslash that is not a valid escape is a
      # COMPILE error in the adopter's whole Jenkinsfile -- not a runtime one, and not confined to
      # this stage. The first draft of this block wrote a shell backtick as a backslash-backtick and
      # did exactly that. Second: the ONLY transformation either side applies is joining a backslash-
      # newline, and BOTH apply it, so bash reading this raw text and Groovy handing it to sh are
      # behaviourally identical -- NOT byte-identical: Groovy has already joined the continuations,
      # so the two differ by a few bytes. That equivalence is why a test can extract this and run it.
      # Use single quotes where the shell needs a quote. There is a test that fails on a backslash.
      WANT=$(python3 -c 'import json;print(json.load(open("darnlink-gate.json")).get("recipe_sha256",""))')
      if [ -n "$WANT" ]; then
        # A digest is 64 lowercase hex. Anything else is a copied placeholder or a truncated paste,
        # and without this it would be reported as a checksum MISMATCH -- sending the reader to hunt
        # a tampered download when they simply pasted the wrong thing.
        # Uppercase is a REAL digest, not a typo: PowerShell's Get-FileHash returns A-F, and this
        # page tells Windows agents to fetch the recipe. Rejecting it would call a correct value
        # "not a digest" and tell the reader to replace it -- false, and it breaks a real adopter.
        WANT=$(printf '%s' "$WANT" | tr 'A-F' 'a-f')
        case "$WANT" in
          *[!0-9a-f]* | "" ) BAD=1 ;;
          * ) [ ${#WANT} -eq 64 ] && BAD= || BAD=1 ;;
        esac
        if [ -n "$BAD" ]; then
          echo "recipe_sha256 is not a sha256 digest (expected 64 lowercase hex): $WANT" >&2
          echo "  if that looks like the placeholder from recipes/README.md, replace it with a real digest." >&2
          rm -f "$WORKSPACE/.darnlink-gate"
          exit 1
        fi
        # macOS ships shasum, not sha256sum. Without this the step dies with command-not-found on a
        # mac agent -- fail-closed, so no false green, but it breaks a consumer who works today.
        if command -v sha256sum >/dev/null 2>&1; then
          GOT=$(sha256sum "$WORKSPACE/.darnlink-gate" | cut -d" " -f1)
        else
          GOT=$(shasum -a 256 "$WORKSPACE/.darnlink-gate" | cut -d" " -f1)
        fi
        if [ "$GOT" != "$WANT" ]; then
          # THREE causes, most probable FIRST -- the mundane one is the one that actually happens.
          echo "recipe checksum mismatch for $VER -- most likely someone bumped 'ref' without re-sealing 'recipe_sha256' next to it; otherwise the tag moved, or the download was tampered with" >&2
          echo "  expected $WANT" >&2
          echo "  got      $GOT" >&2
          echo "  re-seal: curl -fsSL 'https://raw.githubusercontent.com/txemi/darnlink/$VER/recipes/darnlink-gate' | sha256sum | cut -d' ' -f1" >&2
          rm -f "$WORKSPACE/.darnlink-gate"   # never leave an unverified script on disk
          exit 1
        fi
        echo "recipe checksum OK: $GOT"
      else
        # Say so. Silence reads as "verified", which is the failure this step exists to prevent.
        echo "darnlink-gate.json declares no recipe_sha256 -- THIS DOWNLOAD IS NOT VERIFIED. See recipes/README.md." >&2
      fi
      chmod +x "$WORKSPACE/.darnlink-gate"
      "$WORKSPACE/.darnlink-gate"          # scope=repo from darnlink-gate.json
      rm -f "$WORKSPACE/.darnlink-gate"
  '''
}

// A Windows agent: the same shell, written to the workspace and run by the bash of Git for Windows,
// whose launcher puts its own tools (curl, sha256sum, coreutils) on PATH. --noprofile --norc: the
// agent's bash profile is not part of the gate. PYTHONUTF8=1: the recipe's Python reads and prints
// UTF-8 whatever the console code page, so a non-ASCII file name is judged, not mangled.
// Forward slashes in the path on purpose: this file carries no backslash (see the note in the shell).
def windowsBash(String script) {
  String bash = env.DARNLINK_GATE_BASH ?: '%ProgramFiles%/Git/bin/bash.exe'
  writeFile file: '.darnlink-gate-step.sh', text: script, encoding: 'UTF-8'
  try {
    withEnv(['PYTHONUTF8=1']) {
      bat('@"' + bash + '" --noprofile --norc .darnlink-gate-step.sh')
    }
  } finally {
    bat('@"' + bash + '" --noprofile --norc -c "rm -f .darnlink-gate-step.sh"')
  }
}
