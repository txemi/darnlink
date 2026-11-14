// EXAMPLE Jenkins stage — darnlink link gate, the SERVER-SIDE wall (piece 4, self-hosted).
//
// The natural home for the wall on a PRIVATE repo where hosted CI minutes are billed or branch
// protection is unavailable: a self-hosted agent runs the same check with no billing.
//
// The shell lives in ONE place, the shared-library step vars/darnlinkGate.groovy: it derives the pin
// from darnlink-gate.json, fetches that recipe from the PUBLIC darnlink repo (no credentials),
// verifies recipe_sha256 BEFORE running it, and runs it FAIL-CLOSED.
//
// WITH the library (declared once on the controller as a global pipeline library named `darnlink`;
// see the header of vars/darnlinkGate.groovy): put `@Library('darnlink') _` at the top of your
// Jenkinsfile and this stage into its `stages { … }`.
//
// WITHOUT it: replace `darnlinkGate()` with the `sh` block of vars/darnlinkGate.groovy, inside
// `withEnv(['DARNLINK_GATE_FAIL_CLOSED=1']) { … }`.

stage('darnlink gate (links)') {
  steps {
    darnlinkGate()
  }
}
