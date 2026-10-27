---
name: release-guru
description: Cut a release of this repo. Picks the next version from CHANGELOG.md, opens the release pull request, then tags the merge commit and checks the GitHub release. Use when someone wants to release, publish a version, or cut or tag a release of NetBird Docker Host.
---

# Cut a release

For maintainers of this repository. Before anything else, apply [Where am I?](../../../AGENTS.md#where-am-i), [Secret files](../../../AGENTS.md#secret-files) and [Confirm or refuse](../../../AGENTS.md#confirm-or-refuse) from `AGENTS.md`. The procedure and the version table are in [Releasing](../../../CONTRIBUTING.md#releasing).

Being asked to run this skill is the request to branch, commit and open the release pull request. Pushing the branch and pushing the tag are each confirmed first. A release takes two sittings: prepare now, publish after the pull request merges.

## Before you start

- **Not on a deployment.** Stop and ask for a separate clone if `docker ps --format '{{.Names}}'` lists `netbird-server`, or if `test -e netbird-server/.env` succeeds (never open that file). A NetBird client running here is no reason to stop.
- **Push access.** `gh repo view --json viewerPermission` must show `WRITE`, `MAINTAIN` or `ADMIN`; tagging needs it. Otherwise stop.
- **Clean start.** On `main` with a clean tree, `git pull --ff-only --tags`, and `gh auth status` logged in.

## Which sitting

Work out where the release stands: `gh pr list --state all --limit 10 --json number,headRefName,state` shows the recent pull requests, and the `release/` branches among them are this skill's.

- An open pull request from a `release/` branch: go to [While the pull request is open](#while-the-pull-request-is-open).
- A merged release pull request whose `vX.Y.Z` tag does not exist yet (`git tag -l vX.Y.Z` prints nothing): go to [Publish](#publish).
- Otherwise: [Prepare](#prepare) a new release.

## Prepare

1. The newest `## [x.y.z]` heading in `CHANGELOG.md` names the newest tag, `git describe --tags --abbrev=0`. If not, stop and explain: a release was tagged without its changelog section, or the other way round.
2. Read `## [Unreleased]`. If it is empty, there is nothing to release: say so and stop.
3. Propose the next version with the table in [Releasing](../../../CONTRIBUTING.md#releasing), showing the section and the subsections that decided it. Never propose `1.0.0` on your own; the user decides when. Wait for a yes, or for another number.
4. Branch `release/vX.Y.Z` from `main` and edit `CHANGELOG.md`: the entries move under `## [X.Y.Z] - YYYY-MM-DD` with today's date, an empty `## [Unreleased]` stays above it, and the links at the bottom change as `CONTRIBUTING.md` says.
5. Preview the release notes: run the awk program from the "Extract release notes" step of `.github/workflows/release.yml` against the edited file, with `v` set to `X.Y.Z`, and show the user the output. It must be the new section and nothing else.
6. Run every command in [Checks before a repo change](../../../AGENTS.md#checks-before-a-repo-change); `tests/test_changelog.py` checks the new shape.
7. Stage `CHANGELOG.md` by name and commit `chore: release X.Y.Z`.
8. Show `git config user.name`, `git config user.email` and `gh auth status`, ask, then push the branch and open the pull request with `gh pr create`. Its body follows `.github/pull_request_template.md` and includes the notes preview.

## While the pull request is open

If another pull request merges first and `CHANGELOG.md` conflicts, rebase `release/vX.Y.Z` onto `main` and move the new `## [Unreleased]` lines into the release section: they are part of the code being released. If that changes the bump (a patch release gains an Added line), propose the new number and wait for a yes, then change the heading and links, and keep the branch name: a pull request cannot change its branch, and a new branch would orphan it. Run the checks again, ask, and push with `git push --force-with-lease`.

## Publish

After the release pull request merges:

1. Switch to `main` and `git pull --ff-only`.
2. Find the merge commit with `gh pr view <number> --json mergeCommit`. `git show <sha>:CHANGELOG.md` must hold `## [X.Y.Z]`.
3. The tag must not exist yet: `git tag -l vX.Y.Z` and `git ls-remote --tags origin vX.Y.Z` print nothing.
4. CI must have passed on that commit: `gh run list --commit <sha>` shows the CI workflow with `success`.
5. Ask, then tag that commit, not the newest one on `main`, and push only the tag: `git tag -a vX.Y.Z -m "vX.Y.Z" <sha>`, then `git push origin vX.Y.Z`.
6. Find the Release run with `gh run list --workflow release.yml --commit <sha> --json databaseId,status,conclusion` (it can take a few seconds to appear), then watch it with `gh run watch <id> --exit-status`. A non-zero exit means it failed: go to the next section. Otherwise run `gh release view vX.Y.Z`: its notes must match the `## [X.Y.Z]` section.

## If the Release workflow fails

Show the failing step's log and stop. The tag is public now, so deleting or moving it needs the user's yes, as [Confirm or refuse](../../../AGENTS.md#confirm-or-refuse) says. Once the cause is fixed in a merged pull request, ask the user whether to move the tag to the fix or to release the fix as the next patch version.
