# Publishing runbook (v0.1.0)

Everything here is a **deliberate, human-gated action**: nothing in this repo
is public until you perform these steps. Work top to bottom; each phase says
what it changes and how to back out.

## 0. Pre-flight (local, safe)

```sh
uv run ruff check src tests && uv run pytest -q     # must be green
uv run macaulay2-mcp selftest                        # must pass
uv build                                             # dist/ artifacts build
curl -s -o /dev/null -w "%{http_code}\n" https://pypi.org/pypi/macaulay2-mcp/json
#   ^ 404 expected = name still free. 200 would mean someone claimed it;
#     stop and pick a different [project] name in pyproject.toml.
```

Version bump checklist (until finding F5 makes it dynamic): the version must
match in **both** `pyproject.toml` (`[project] version`) and
`src/macaulay2_mcp/__init__.py` (`__version__`).

Optional rehearsal on TestPyPI (uses a token from test.pypi.org — trusted
publishing is configured separately there and is not required for v0.1):

```sh
uv publish --publish-url https://test.pypi.org/simple/ \
  --username __token__ --password "$TEST_PYPI_TOKEN"
uvx --isolated --index-url https://test.pypi.org/simple/ \
   --extra-index-url https://pypi.org/simple macaulay2-mcp selftest
```
Backout: delete the release on test.pypi.org (account → project → versions).

## 1. Create the two GitHub repos (public)

These two folders are **independent repositories** (no submodules). Install
the helper (`brew install gh && gh auth login`) or create the repos on the
web — then from each directory:

```sh
# repo 1: the server
cd m2_mcp_project
git remote add origin https://github.com/<GH-USER>/m2_mcp_project.git
git push -u origin main

# repo 2: the Binder demo (must be PUBLIC — mybinder.org builds from it)
cd ../m2-mcp-binder
# first replace YOUR-USERNAME in README.md, postBuild, demo.ipynb:
#   grep -rn YOUR-USERNAME .
git remote add origin https://github.com/<GH-USER>/m2-mcp-binder.git
git push -u origin main
```

Backout: `git remote remove origin` (local untouched); delete the empty repos
on GitHub any time.

Then in the server repo, replace the remaining `YOUR-USERNAME` placeholders
(README badges/links) with `<GH-USER>` and commit; GitHub Actions CI runs on
push (macOS brew + Ubuntu PPA, both M2 1.26) — wait for green.

## 2. PyPI: account + trusted publishing (no token to store)

1. Create an account at pypi.org (enable 2FA if prompted).
2. Account settings → **Publishing → Add a new publisher**:
   - Repository: `<GH-USER>/m2_mcp_project`
   - Workflow name: `release.yml`
   - Environment name: `pypi`
   - Project name: `macaulay2-mcp`
   (This "pending publisher" is allowed before the project exists; the first
   trusted upload creates it.)
3. In GitHub: Settings → Environments → create environment **`pypi`** (no
   secrets needed). If branch protection prompts, allow `main`.

Backout: delete the pending publisher on PyPI; remove the environment.

## 3. Release

```sh
git tag v0.1.0
git push origin v0.1.0
```
The `Release` workflow builds and publishes via OIDC automatically. Watch it
in Actions.

Backout: `git tag -d v0.1.0 && git push origin :refs/tags/v0.1.0`, and yank
the release on PyPI (project → versions → yank) — yanking discourages new
installs without deleting history; full deletion is possible within the
PyPI grace window.

## 4. Post-release verification

```sh
uvx macaulay2-mcp selftest          # the exact command from the README
```
- Re-push the Binder repo (its postBuild prefers PyPI and falls back to the
  git URL automatically), then click the Launch-on-Binder badge.
- The README "Add to LM Studio" button and all `uvx` snippets now work as
  written.
- Optional: paste the release blurb to the M2 Zulip / Google group, and ask
  the LM Studio team about their curated catalog.

## Notes

- Release CI does not run the M2-dependent tests; they run in `ci.yml` on
  every push (both OSes). Trusted publishing requires the tag push to come
  from the repo configured in step 2 — forks/tags elsewhere will fail loud,
  which is the point.
