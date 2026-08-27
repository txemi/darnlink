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
      # ⚠️ NO BACKSLASH IN THIS BLOCK EXCEPT A LINE CONTINUATION (a backslash immediately before a
      # newline, as on the curl above -- Groovy and the shell both just remove it, so they agree).
      # That rule is load-bearing twice over. Groovy processes
      # escape sequences inside a triple-quoted string, so a backslash that is not a valid escape is a
      # COMPILE error in the adopter's whole Jenkinsfile -- not a runtime one, and not confined to
      # this stage. The first draft of this block wrote a shell backtick as a backslash-backtick and
      # did exactly that. Second: with no backslashes the raw text of this block is byte-identical to
      # what Groovy hands to the shell, which is the only reason a test can extract it and run it.
      # Use single quotes where the shell needs a quote. There is a test that fails on a backslash.
      WANT=$(python3 -c 'import json;print(json.load(open("darnlink-gate.json")).get("recipe_sha256",""))')
      if [ -n "$WANT" ]; then
        # A digest is 64 lowercase hex. Anything else is a copied placeholder or a truncated paste,
        # and without this it would be reported as a checksum MISMATCH -- sending the reader to hunt
        # a tampered download when they simply pasted the wrong thing.
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
}
