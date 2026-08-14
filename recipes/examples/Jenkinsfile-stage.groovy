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
      chmod +x "$WORKSPACE/.darnlink-gate"
      "$WORKSPACE/.darnlink-gate"          # scope=repo from darnlink-gate.json
      rm -f "$WORKSPACE/.darnlink-gate"
    '''
  }
}
