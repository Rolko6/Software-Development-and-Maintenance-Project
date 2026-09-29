# Continuous integration

This describes `.github/workflows/ci.yml` and `.github/workflows/docs-check.yml`:
what each job does, what it proves and does not prove, how to reproduce it
locally, how to read a failure, and how to add a new check. It is part of
Work Package 4 ("Automate build and deployment", [project plan](../project-plan.md)).
For publishing images to GHCR, see `.github/workflows/publish.yml` (a
separate workflow triggered by pushes to `main`, `v*.*.*` tags and manual
dispatch, never by `develop`; it is not covered here). For running
the stack, see the [README](../../README.md); for a shared test
deployment, see [deployment.md](deployment.md).

## When these run

Both workflows trigger on:

- `pull_request` targeting `main` or `develop`
- `push` to `main` or `develop`

Each workflow has its own `concurrency` group keyed by branch/ref, so a new
push cancels an in-progress run of the same workflow on the same ref rather
than queuing behind it. Both request only `permissions: contents: read` —
neither pushes images, writes packages, or needs any repository secret.

## `ci.yml` jobs

### `lint` — lint / static checks

**Does:** checks out the repository, then runs `python -m compileall` over
the whole tree (excluding `.venv/`, `.git/`, `.trash/`) and `ruff check .`
using a version of ruff pinned inline in the workflow (`env.RUFF_VERSION`),
installed with `pip` at run time.

**Proves:** every tracked Python file parses and byte-compiles cleanly
under Python 3.12, and passes ruff's default rule set (unused imports and
variables, obvious bugs, common style issues).

**Does not prove:** that any code actually runs correctly, that imports
resolve against a real dependency set (compiling does not execute a
module's imports), or that types are consistent (no type checker is run).

**Reproduce locally:**

```bash
python -m compileall -q -f . -x '(\.venv|\.git|\.trash)/'
pip install "ruff==0.14.5"   # match env.RUFF_VERSION in ci.yml
ruff check .
```

### `test` — unit tests (matrix: `cloud`, `gateway`, `device`)

**Does:** for each service independently, verifies that
`<service>/requirements-dev.txt` and `<service>/tests/` exist (failing the
job with a clear `::error::` if not, rather than silently reporting green
with nothing checked), installs that service's own dev dependencies, runs
`pytest` from inside the service directory with `--junitxml=unit-report.xml`,
appends a small pass/fail table to the job summary via
`.github/scripts/junit_summary.py`, and uploads the JUnit report as an
artifact (`junit-cloud`, `junit-gateway`, `junit-device`) even when the run
fails.

**Proves:** each service's own unit test suite passes in isolation, using
only that service's pinned dependencies.

**Does not prove:** that the services work together over HTTP, that Docker
images build, or that the Compose stack starts. That is `build`, `compose-validate`,
and `smoke`.

**Reproduce locally** (per service; repeat for `cloud`, `gateway`, `device`):

```bash
cd gateway
pip install -r requirements-dev.txt
pytest -ra --junitxml=unit-report.xml
```

Or run all three in one combined pass/fail report: `./scripts/run-unit-tests.sh`
(owned by the testing task; see that script for details).

### `root-tests` — root suites (matrix: `crypto`, `reliability`, `protected_path`, `tooling`)

**Does:** runs each root-level suite under `tests/` in its own job and its
own `python -m pytest tests/<suite>` process on Python 3.12, from the
repository root. Installs `requirements-dev.txt`, which includes
`gateway/requirements.txt` and `cloud/requirements.txt` because these suites
import both services' code in-process, then checks that `fastapi`, `httpx`
and `cryptography`'s `mlkem` import before pytest starts. Writes a job
summary listing every failed, errored and skipped test with its reason,
uploads the JUnit report as `junit-root-<suite>`, and enforces a skip
budget and an expected-failure (xfail) budget per suite (`max_skipped` and
`max_xfailed` in the matrix): the job fails if a suite skips, or expects to
fail, more tests than its budget. Every budget is 0 except two, each of
which waits on a group decision named in the test's reason:
`protected_path` may skip 1 (the module-level skip of
`test_protected_path_contract.py`), and `crypto` may xfail 1 (the strict
xfail recording that the device id travels in clear,
`test_protected_path_session.py`). The budget check is
`.github/scripts/junit_summary.py --max-skipped/--max-xfailed`, tested by
`tests/tooling/test_junit_summary.py`.

| Suite | What it checks |
| --- | --- |
| `crypto` | ML-KEM against NIST ACVP known-answer vectors and FIPS 203 properties; the gateway and cloud secure-channel code (handshake, secure data, replay, mode switch); the protected-path requirements ported to the session design (`test_protected_path_session.py`) |
| `reliability` | Validation rules, bounded retry, readiness and bounded storage in the gateway and cloud apps, in-process |
| `protected_path` | Source scan for classical key agreement and the ML-KEM library pin; the original sessionless contract (skipped) |
| `tooling` | Regression tests for `.github/scripts/check_docs.py` and the budget check in `.github/scripts/junit_summary.py` |

**Why separate processes:** `gateway/app` and `cloud/app` are both packages
named `app`. `tests/crypto` and `tests/reliability` each load both under
private aliases and manipulate `sys.modules` and `os.environ` to do it, so
running them in one interpreter would make results depend on collection
order. `tests/integration` is excluded because it needs the running stack;
`smoke` runs it.

**Proves:** the four suites pass from a clean checkout with only the pinned
dependencies, and no new skip appears silently.

**Does not prove:** anything about the containers (see `build` and
`smoke`), or side-channel resistance of the ML-KEM implementation (see
[ML-KEM verification](../testing/ml-kem-verification.md)).

**Reproduce locally:**

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
for suite in crypto reliability protected_path tooling; do
  .venv/bin/python -m pytest "tests/$suite" -ra || echo "FAILED: $suite"
done
```

### `compose-validate` — validate the Compose file

**Does:** `docker compose config --quiet`.

**Proves:** `docker-compose.yml` parses and resolves (service references,
environment interpolation, build contexts) without error.

**Does not prove:** that any image builds, that a container starts, or
that the application behaves correctly. Compose has no health checks
configured for these services (a documented, deliberate limitation — see
the README's "Known limitations"), so this check cannot and does not wait
for readiness.

**Reproduce locally:**

```bash
docker compose config --quiet
```

### `build` — build images (matrix: `cloud`, `gateway`, `device`)

**Does:** for each service, sets up Docker Buildx and builds that
service's image with `docker/build-push-action`, `push: false`, using the
GitHub Actions cache backend (`cache-from`/`cache-to: type=gha`) scoped
per service (`scope=build-<service>`) so the three matrix legs do not
overwrite each other's cache. Runs only after `lint` and `compose-validate`
succeed, to avoid spending build minutes on a change that already fails a
cheaper check.

**Proves:** each of the three Dockerfiles builds successfully from a clean
checkout on `linux/amd64` (the GitHub-hosted runner's platform; no other
platform is targeted).

**Does not prove:** that the built image runs correctly, or that the three
services interoperate. It also does not push or publish anything — that is
`.github/workflows/publish.yml`'s job, triggered separately on pushes to
`main` and version tags.

**Reproduce locally** (requires Docker):

```bash
docker buildx build ./cloud   -t local/cloud:ci
docker buildx build ./gateway -t local/gateway:ci
docker buildx build ./device  -t local/device:ci
```

(Or simply `docker compose build`, which builds all three from
`docker-compose.yml` but does not exercise the GitHub Actions cache
backend used in CI — that only matters for CI's build speed, not for
whether the build succeeds.)

### `smoke` — smoke test against the real Compose stack

**Does:** runs only after `build`, `test` and `root-tests` succeed. Verifies
`requirements-dev.txt`, `scripts/smoke-test.sh`, `pytest.ini`, and
`tests/integration/` exist (failing loudly if not), installs the root dev
dependencies, then runs `scripts/smoke-test.sh --junitxml=smoke-report.xml`.
That script (owned by the testing task, not this one) already:

1. Runs `docker compose config --quiet`.
2. `docker compose up --build -d`. This rebuilds the images; the ones
   `build` produced are not reused.
3. Polls both `/health` endpoints (up to 90s) — since Compose has no
   health checks configured, this script's own polling is what "wait for
   the health endpoints" means here.
4. Runs the `tests/integration` suite against the live stack, which covers
   the README's known-reading check, the invalid-device-id check (expects
   HTTP 422), the gateway metrics counters, and the simulated device
   reaching the cloud end-to-end.
5. On any failure, dumps `docker compose logs` before tearing down.
6. Always runs `docker compose down -v --remove-orphans` on exit, success
   or failure.

**Proves:** the full device → gateway → cloud flow works end-to-end from a
clean `docker compose up --build`, including the specific failure-mode
checks in the README ("Manual failure checks" → invalid device ID).

**Does not prove:** production-scale reliability, behavior under real
network latency/loss, security properties (the link is plain HTTP — see
the README's "Known limitations"), or anything about the cloud-outage /
recovery scenario (that check stops the cloud container mid-run and is
better suited to a manual or separate scheduled check, not this
pipeline). Stored readings are in-memory and are lost with the container;
this job's teardown (`down -v`) is deliberate and does not "lose" evidence
that matters, but treat that as a reminder for the shared test environment
too (see [deployment.md](deployment.md), "Data-loss caveat").

**Reproduce locally** (requires Docker; do not run this against ports
already in use):

```bash
pip install -r requirements-dev.txt
bash scripts/smoke-test.sh
```

## `docs-check.yml` job

**Does:** runs `.github/scripts/check_docs.py`, which:

- Lists every tracked *and* untracked Markdown file (untracked files do not
  appear in a normal `git diff`, so they are included explicitly).
- Parses local (non-`http(s)`/`mailto:`) links and validates that the
  target file exists and, where a `#anchor` is present, that a heading in
  the target file slugifies to that anchor (GitHub's heading-anchor rules).
- Confirms the root `CLAUDE.md` contains exactly one standalone
  `@AGENTS.md` import line and that `AGENTS.md` exists.
- Confirms code fences (`` ``` `` / `~~~`) are balanced per file.
- Flags any line with trailing whitespace.
- Runs `git diff --check` — against the pull request's base commit on a
  `pull_request` event (via `github.event.pull_request.base.sha`, with
  `fetch-depth: 0` so that commit is available locally), or against the
  working tree on a `push` event (so on a clean checkout it trivially
  passes; it is mainly useful when run locally against uncommitted
  changes).

**Proves:** the documentation is internally consistent at this snapshot —
no dangling local links/anchors, the Claude Code import is intact, no
stray whitespace-only diffs.

**Does not prove:** that documentation is factually accurate, up to date
with the code it describes, or complete. Reading the content is still
necessary.

**Reproduce locally:**

```bash
python .github/scripts/check_docs.py
# Or, to check a diff against a specific base (mirrors the PR-event behavior):
python .github/scripts/check_docs.py --diff-ref origin/main
```

The script depends only on the standard library and `git`; no
`pip install` is needed to run it.

## Reading a failure

- **`lint`:** the failing step's log names the offending file and line
  (`compileall` prints a `SyntaxError` with a traceback; `ruff` prints
  `path:line:col: CODE message`).
- **`test`:** open the job summary for a one-line pass/fail table per
  service, or download the `junit-<service>` artifact for the full
  per-test XML report.
- **`compose-validate`:** the step log is Compose's own error message
  (e.g. an unresolved `${VAR}` or a YAML syntax error) with a line
  reference into `docker-compose.yml`.
- **`build`:** the failing step's log is the Docker/Buildx build output;
  look for the last successful layer and the first failing `RUN`/`COPY`.
- **`smoke`:** the step log includes the full `docker compose logs` dump
  (added by `scripts/smoke-test.sh`'s failure trap) directly above the
  script's own exit message, plus the `smoke-report` artifact if pytest
  produced one before failing.
- **`docs-check`:** the step log lists every violation as
  `path:line: message`; there is no artifact, the log is the report.

## Adding a new check

1. Decide whether it belongs in `ci.yml` (fast, per-PR) or as its own
   workflow (like `docs-check.yml`) if it has a very different trigger or
   dependency footprint.
2. If it needs a new GitHub Action, resolve it with Context7
   (`resolve-library-id` then `query-docs`) or check the action's own
   repository/marketplace page — do not guess a version from memory — and
   pin it to a released major version tag (or a commit SHA), never `@main`
   or `@latest`.
3. Add the step with least-privilege `permissions` (most checks need only
   `contents: read`); add a new job only if the check has a materially
   different dependency set or should run in parallel/matrix.
4. If the check depends on files owned by another task's directory
   convention (as `test` and `smoke` do here), make it fail loudly with an
   explicit `::error::` message when a required file is missing — never
   let it silently no-op.
5. Make sure the check is runnable locally with a documented command
   (extend this file), so a contributor is not forced to push to a branch
   to find out whether it will pass.
6. Update this file's job-by-job list and the "what it proves / does not
   prove" pair for the new check.
