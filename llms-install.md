# Install NetBird Docker Host with a coding agent

This file is for a coding agent (Claude Code, Codex, Pi, OpenCode or any other). The user pasted a line asking you to follow it: install the self-hosted NetBird server from this repository, or join a VM to one as a peer. People reading this should use the [README](README.md) instead.

Work through the steps in order.

## 1. Get the code

If the current directory or one of its parents is already a clone of this repository (`git remote get-url origin` names `terraapply/NetBird-Docker-Host`), use that clone as it is. Do not switch its branch or pull.

Otherwise clone it into the current directory, as the README does:

```bash
git clone https://github.com/terraapply/NetBird-Docker-Host.git
```

If `git` is missing, ask the user to install it and stop until they have.

## 2. Load the rules

Read `AGENTS.md` in the clone, all of it, before you run anything else. Your harness was started outside the clone, so it has not loaded `AGENTS.md` or the skills on its own: read them as files. From here on its hard rules, [Secret files](AGENTS.md#secret-files) and [Confirm or refuse](AGENTS.md#confirm-or-refuse) bind you. Where it and this file disagree, `AGENTS.md` wins.

## 3. Work out where you are

Run the read-only checks in [Where am I?](AGENTS.md#where-am-i). Tell the user what you concluded and wait for them to confirm before the next step. On a laptop, the clone stays there for reading, and every command for the VM goes to the user as a short block.

## 4. Pick the job

Ask the user which one they want:

| The user wants | Read and follow |
|---|---|
| The NetBird server (control plane) | [`.agents/skills/netbird-install-server/SKILL.md`](.agents/skills/netbird-install-server/SKILL.md) |
| A VM joined to a running server as a peer | [`.agents/skills/netbird-install-agent/SKILL.md`](.agents/skills/netbird-install-agent/SKILL.md) |

The server comes first: a peer needs a running server and a setup key from its dashboard.

Read the whole `SKILL.md`, then follow it to the end, in order. Read the README sections it links from the clone. Stop wherever it asks for evidence or the user's confirmation. If step 3 found a server or peer that is already running, ask what the user wants before installing anything: [`netbird-troubleshoot`](.agents/skills/netbird-troubleshoot/SKILL.md) fixes a broken one, [`netbird-maintain`](.agents/skills/netbird-maintain/SKILL.md) upgrades or backs one up.

Never ask the user to paste a secret or a setup key into the chat.

## 5. Hand over

When the skill is done, tell the user:

- what was installed, and the path of the clone
- that next time they can start their agent inside the clone, where it reads `AGENTS.md` and the skills listed there
- which skill comes next: `netbird-install-agent` for more peers, `netbird-maintain` for backups and upgrades, `netbird-troubleshoot` when something breaks
