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

## 1a. History polish (local, run before step 1; soak tests must NOT be running)

`git rebase -i --root` with this pick/squash map (28 → 14 commits, oldest
first; `s` = squash into the commit above; refresh short hashes before
running — `git log --oneline --reverse`):

```
pick d856807  base kernel + 7 tools + selftest + tests
pick 7393916  E2E ...        s 0192bea (stop tracking results)
                             s d5f5632 (assert stderr)
                             s bdf0353 (assert server results)
                             s 3a52812 (GPU-aware modes)
                             s d71471f (LM Studio README section)
pick 79900a7  stderr merge + golden dataset
pick 09f8fa4  run_script trailing-prompt strip
pick 8de1cc4  load_package policy
pick c78ad09  m2_interrupt
pick 9525c92  loops/parallel fan-out   s 3ea50ee (gitignore notes/)
pick 956ea44  brew tap commands + inform-don't-direct
pick 39a5f00  stop_on_error + error menu
pick f2da462  OS-call gate             s c3b2bdc (journal) s 18c1639 (gate/journal docs)
pick 356259b  trusted publishing + PUBLISHING.md
pick 8e79013  marker/splitter fixes    << EDIT: `git rm battery_run.py` here
pick 558a33d  battery artifacts        s 8ddfe43 (author voice) s b788f05 (LaTeX task + soak)
                                   s 635f09f (soak map runbook) s 359fbe5 (soak results)
                                   s ec43729 (soak pairing fix) s 85ac3b7 (feedback + unwrap)
pick <LIC>     license: GPL-3.0-or-later + CITATION.cff + author (own final commit)
```

Then identity + trailers on the whole history with `git filter-repo`:
author/committer `Youngsu Kim <21338460+youngsu-Kim@users.noreply.github.com>`;
message callback: drop any `Co-Authored-By: opencode` line, append
`Assisted-by: Qwen 3.8 Flash Next (hosted by NRP)`.

Verify before push: `git log --all --format='%ae %ce'` shows only noreply;
`git log --all --stat | grep battery_run` empty; `uv run pytest -q` +
`ruff check` + `selftest` green. Safety branch first: `git branch pre-polish`.
License decision (2026-09-06): **GPL-3.0-or-later** — the family Macaulay2
itself names in its copyright statement (free to use, including commercially;
distributed derivatives must stay open; SaaS hosting is intentionally left
permitted). Binder repo (already polished to 1 commit `e8e4648`): add the same
LICENSE, amend it into that single commit with the identity/trailers already
set, and re-run `git log` verification.

Invariant: after the rebase, `git diff pre-polish HEAD --stat` may show ONLY
the expected changes (battery_run.py removed, placeholders renamed, this file).
Anything else = a rebase conflict was resolved wrong; restart from the branch.

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
