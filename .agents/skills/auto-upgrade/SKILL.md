---
name: auto-upgrade
description: Find newer releases of everything this repo pins (NetBird, Traefik, Dex, Postgres, dev tools, GitHub Actions), upgrade them, run the checks and open one pull request per group. Use when someone wants to check for updates or bump versions in the repo, not upgrade a running server.
---

# Upgrade the repo's pinned versions

This skill changes the repository, not a running server: upgrading a deployment is `netbird-maintain`. Before anything else, apply [Where am I?](../../../AGENTS.md#where-am-i), [Secret files](../../../AGENTS.md#secret-files) and [Confirm or refuse](../../../AGENTS.md#confirm-or-refuse) from `AGENTS.md`. The procedure and its rules are in [Keeping versions current](../../../CONTRIBUTING.md#keeping-versions-current); follow it, with the agent rules below.

Being asked to run this skill is the request to create branches, commit and open pull requests. Every push is still confirmed first.

## Before you start

- **Not on a deployment.** On the server VM the deployment is itself a clone, and checking out an unmerged branch there means the next `./deploy.py` renders unreviewed templates. Stop and ask the user to work from a separate clone if `docker ps --format '{{.Names}}'` lists `netbird-server`, or if `test -e netbird-server/.env` succeeds (never open that file). The NetBird client running on this machine is no reason to stop: maintainers' laptops often run it.
- **Push access.** `gh repo view --json viewerPermission` must show `WRITE`, `MAINTAIN` or `ADMIN`. Otherwise stop: the user can still run the script and follow `CONTRIBUTING.md` by hand from a fork.
- **Clean start.** On `main` with a clean tree, `git pull --ff-only`, `.venv` set up as in [Setup](../../../CONTRIBUTING.md#setup), and `gh auth status` logged in.
- **No duplicates.** If `gh pr list --state open` already holds an upgrade for a group, from this skill (`upgrade/` branches) or from Renovate (`renovate/` branches), skip that group and say so.

## 1. Look

Run `python3 scripts/check_versions.py` and show the user the table. Then read `python3 scripts/check_versions.py --json` for each row's `candidates`, `notes`, `locations` and `release_notes`. A row with an `error` is not upgraded; a GitHub rate limit goes away with `GITHUB_TOKEN` set.

## 2. Plan

For each group, propose the target versions and wait for the user's yes before any edit.

- For every `major` jump, read the release notes (`release_notes`) of every release between the current version and the target, oldest first. `jump` already counts a 0.x minor as major. Write down anything that touches this repo: `netbird.yaml` keys and templates, environment variables, ports, CLI flags, Traefik labels, Dex connector settings.
- The target is the newest release that needs no change to this repo, with no earlier release needing one either. Report the first release that does need one, with what would have to change, and offer to make that change in its own pull request with `netbird-extend`. Never mix it into the upgrade.
- NetBird: server and client get the same version, the dashboard its own. When server and client stay where they are, so does the dashboard.
- Postgres: `APPLY no` means never. A new major cannot start on the old data directory. Report it and move on.
- Python: only the newest CI version moves; 3.10 stays.
- ruff and yamllint: the PyPI version and the pre-commit `rev` move to the same release.

## 3. One group, one branch

For each group the user approved, branch from an up-to-date `main`: `upgrade/netbird-<version>`, or `upgrade/<group>-<YYYY-MM-DD>` for the others.

1. Edit every line in `locations`, reading each one first: a hit can be unrelated text that contains the same string. `netbird.example.yaml` is a tracked example with no secrets; `netbird.yaml` is never touched.
2. NetBird: the server tag in `netbird.example.yaml` and the client tag in `netbird-agent/docker/docker-compose.yml` stay equal, which `test_client_matches_server_release` checks.
3. Tooling: reinstall with `.venv/bin/pip install -r requirements-dev.txt`, then run `.venv/bin/ruff format .` and `.venv/bin/ruff check --fix .`. If anything still needs a hand edit, drop the group and say why.
4. Run `python3 scripts/check_versions.py --group <group>`: every pin you changed shows the planned version under `CURRENT`, and no row has a `must match`, `differ` or `not found` note. A release you held back, or a Postgres major marked `APPLY no`, still shows as newer; that is expected.
5. Run every command in [Checks before a repo change](../../../AGENTS.md#checks-before-a-repo-change). For `netbird` and `images` the Docker tests must run, not skip; if Docker is missing, say so in the PR body. A failing check drops the group: no PR, and the report says what failed.
6. `netbird` and `images`: add one line under `## [Unreleased]` in `CHANGELOG.md`, for someone running the stack. `tooling` and `actions` add none.
7. Stage the changed files by name, never `git add -A`, and commit with `chore:` (`ci:` for `actions`).

## 4. Push and open the PRs

Show `git config user.name`, `git config user.email` and `gh auth status`, list the branches, and ask once before pushing them all. Open each PR with `gh pr create`, the body following `.github/pull_request_template.md`: old and new versions, release notes links, what the notes said for each major, the commands run and what they printed. For `tooling` and `actions`, say next to the CHANGELOG item that nothing changes for someone running the stack.

## 5. Wait for CI

The local run used one Python; CI runs the whole matrix. Run `gh pr checks <number> --watch` for each PR. Fix on the branch only a failure the upgrade itself caused, and ask before pushing the fix. Otherwise report that the PR should not merge, with the failing log.

## 6. Report

PR links with their CI results, groups skipped and why, releases held back and what they need, and any Postgres major waiting. Remind the user that merging changes the repo only: a running server is upgraded with `netbird-maintain`, then its agents.

Two open PRs that both add a `CHANGELOG.md` line conflict once the first merges. When asked, rebase this skill's open `upgrade/` branches onto `main`, keep both lines, run the checks again, ask, and push with `git push --force-with-lease`.
