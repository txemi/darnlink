// EXAMPLE Jenkins stage — darnlink link gate, the SERVER-SIDE wall (piece 4, self-hosted).
//
// The natural home for the wall on a PRIVATE repo where hosted CI minutes are billed or branch
// protection is unavailable: a self-hosted agent runs the same check with no billing.
//
// INSTALL: drop this stage into your declarative Jenkinsfile's `stages { … }`.
// ASSUMES: `uvx` and `python3` on the agent (the recipe needs python3 anyway to read the json).
//          `astral-sh` installs `uv` into ~/.local/bin; if that is not on PATH, prepend it inside
//          the sh block. The optional token block needs the Credentials Binding plugin.
//
// ONE PIN, and it lives in darnlink-gate.json. Do not hardcode a version here and do not set
// `DARNLINK_REF`: the recipe reads that variable as an ENV OVERRIDE THAT WINS over the json, so a
// tag left in a committed Jenkinsfile silently overrides what the repo asked for, and bumping the
// json does nothing. (The override itself is useful — to try an unreleased build from one branch —
// just never leave it committed.)

// ⚠️ IF your darnlink-gate.json sets `"web": true`, WRAP the `sh` block below in:
//
//     withCredentials([string(credentialsId: 'your-github-readonly-pat', variable: 'GITHUB_TOKEN')]) {
//       sh ''' … '''
//     }
//
// Without a token the web check does NOT fail — every link comes back `web_unverifiable` and the
// stage goes GREEN having verified ZERO web links. A gate that cannot do its job should say so, not
// pass quietly. It is left OUT of the code below so the example runs as copy-pasted: an unresolvable
// credentialsId aborts the stage, and `"web": false` is the default.
stage('darnlink gate (links)') {
  environment {
    DARNLINK_GATE_FAIL_CLOSED = '1'   // the wall must fail closed
  }
  steps {
    sh '''
      set -eu
      ROOT=$(git rev-parse --show-toplevel)

      # `ref` is optional to the recipe (it falls back to a default frozen at v0.7.0 — old, and NOT
      # the version you fetched), but this example insists on it: an unpinned gate is not a wall.
      VER=$(python3 -c 'import json,sys
cfg = json.load(open(sys.argv[1]))
if "ref" not in cfg:
    sys.exit("darnlink-gate.json has no \\"ref\\": pin the version there, not in the Jenkinsfile")
print(cfg["ref"].rsplit("@", 1)[1])' "$ROOT/darnlink-gate.json")

      # OUTSIDE the workspace on purpose: this gate scans the tree recursively, and a stage that
      # litters the workspace is exactly what the section below warns about.
      GATE="${WORKSPACE_TMP:-${TMPDIR:-/tmp}}/.darnlink-gate.$$"
      trap 'rm -f "$GATE"' EXIT        # `set -e` would otherwise skip the cleanup on a red gate

      # -f: fail on a 404 (moved/typo'd tag) instead of writing "404: Not Found" and running garbage.
      curl -fsSL "https://raw.githubusercontent.com/txemi/darnlink/${VER}/recipes/darnlink-gate" -o "$GATE"
      chmod +x "$GATE"
      "$GATE"                            # scope=repo from darnlink-gate.json
    '''
  }
}
