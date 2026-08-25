// EXAMPLE Jenkins stage — darnlink link gate, the SERVER-SIDE wall (piece 4, self-hosted).
//
// The natural home for the wall on a PRIVATE repo where hosted CI minutes are billed or branch
// protection is unavailable: a self-hosted agent runs the same check with no billing. Fetches the
// PINNED recipe from the PUBLIC darnlink repo — no credentials — and runs it FAIL-CLOSED.
//
// INSTALL: drop this stage into your declarative Jenkinsfile's `stages { … }`.
// ASSUMES: `uvx` is available on the agent. `astral-sh` installs `uv` into ~/.local/bin; if it isn't
//          on PATH, prepend it (e.g. `export PATH="$HOME/.local/bin:$PATH"`) inside the sh block.
// The pin is DERIVED from darnlink-gate.json, never repeated here. Two copies of a version number is
// one copy too many: this file carried its own tag and it went stale, because nothing fails when two
// copies drift. Bump `darnlink-gate.json` and both CI surfaces move with it.

stage('darnlink gate (links)') {
  environment {
    DARNLINK_GATE_FAIL_CLOSED = '1'   // the wall must fail closed
  }
  steps {
    sh '''
      set -eu
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
      WANT=$(python3 -c 'import json;print(json.load(open("darnlink-gate.json")).get("recipe_sha256",""))')
      if [ -n "$WANT" ]; then
        GOT=$(sha256sum "$WORKSPACE/.darnlink-gate" | cut -d" " -f1)
        if [ "$GOT" != "$WANT" ]; then
          # THREE causes, most probable FIRST -- the mundane one is the one that actually happens.
          echo "recipe checksum mismatch for $VER -- most likely someone bumped \`ref\` without re-sealing \`recipe_sha256\` next to it; otherwise the tag moved, or the download was tampered with" >&2
          echo "  expected $WANT" >&2
          echo "  got      $GOT" >&2
          echo "  re-seal with: curl -fsSL \"https://raw.githubusercontent.com/txemi/darnlink/$VER/recipes/darnlink-gate\" | sha256sum" >&2
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
}
