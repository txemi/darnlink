// EXAMPLE Jenkins stage — darnlink link gate, the SERVER-SIDE wall (piece 4, self-hosted).
//
// The natural home for the wall on a PRIVATE repo where hosted CI minutes are billed or branch
// protection is unavailable: a self-hosted agent runs the same check with no billing. Fetches the
// PINNED recipe from the PUBLIC darnlink repo — no credentials — and runs it FAIL-CLOSED.
//
// INSTALL: drop this stage into your declarative Jenkinsfile's `stages { … }`.
// ASSUMES: `uvx` is available on the agent. `astral-sh` installs `uv` into ~/.local/bin; if it isn't
//          on PATH, prepend it (e.g. `export PATH="$HOME/.local/bin:$PATH"`) inside the sh block.
// Keep the pinned tag in sync with darnlink-gate.json's `ref`.

stage('darnlink gate (links)') {
  environment {
    DARNLINK_REF              = 'git+https://github.com/txemi/darnlink@v0.7.0'
    DARNLINK_GATE_FAIL_CLOSED = '1'   // the wall must fail closed
  }
  steps {
    sh '''
      set -eu
      # -f: fail on a 404 (moved/typo'd tag) instead of writing "404: Not Found" and running garbage.
      curl -fsSL "https://raw.githubusercontent.com/txemi/darnlink/v0.7.0/recipes/darnlink-gate" \
        -o "$WORKSPACE/.darnlink-gate"
      chmod +x "$WORKSPACE/.darnlink-gate"
      "$WORKSPACE/.darnlink-gate"          # scope=repo from darnlink-gate.json
      rm -f "$WORKSPACE/.darnlink-gate"
    '''
  }
}
