"""Messaging skill auto-installation for Claude Code agents.

Generates and installs a Claude Code skill file that teaches agents
about inter-agent messaging: inbox checks, registration, send/reply,
broadcast, and spawn. Installed per-project to ``{cwd}/.claude/skills/``.

Key functions:
  - install_skill: write skill file to a project directory
  - ensure_skill_installed: check and install if missing/outdated
"""

from __future__ import annotations

from pathlib import Path

import structlog

logger = structlog.get_logger()

SKILL_DIR_NAME = "ccgram-messaging"
SKILL_FILE_NAME = "SKILL.md"

SKILL_CONTENT = """\
---
name: ccgram-messaging
description: Inter-agent messaging — check inbox, send messages, discover peers, broadcast, and spawn agents. Use when idle, when you need help from another agent, or when you want to share status.
---

# Inter-Agent Messaging

You are part of a multi-agent swarm managed by ccgram. Other agents may send you messages. Use these commands to collaborate.

## On Start

Register yourself so other agents can find you:

```bash
ccgram msg register --task "brief description of your current task" --team "team-name"
```

## On Idle (after completing a task or waiting)

Check your inbox for messages from other agents:

```bash
ccgram msg inbox
```

IMPORTANT: When you have peer messages, summarize them to the user first and ask before processing:
"I have N messages from other agents. Here's a summary: [summary]. Should I handle these?"

Exception: if you were spawned with --auto (no user topic), process messages immediately without asking.

## Sending Messages

Find peers:

```bash
ccgram msg list-peers
ccgram msg find --team backend --provider claude
```

Send a message (returns immediately):

```bash
ccgram msg send <peer-id> "your message" --subject "topic"
```

Send and wait for a reply (blocks until reply or timeout):

```bash
ccgram msg send <peer-id> "question?" --wait
```

Reply to a received message:

```bash
ccgram msg reply <msg-id> "your answer"
```

## Broadcasting

Send a notification to all matching peers:

```bash
ccgram msg broadcast "status update" --team backend
ccgram msg broadcast "breaking change in API" --provider claude
```

## Spawning New Agents

Request a new agent for a specific task:

```bash
ccgram msg spawn --provider claude --cwd ~/project --prompt "implement feature X"
```

This requires human approval via Telegram unless --auto is set.
"""


def _skill_dir(cwd: Path) -> Path:
    return cwd / ".claude" / "skills" / SKILL_DIR_NAME


def _skill_path(cwd: Path) -> Path:
    return _skill_dir(cwd) / SKILL_FILE_NAME


def install_skill(cwd: Path) -> bool:
    """Write the messaging skill file to a project directory.

    Returns True if the file was written (new or updated),
    False if it already exists with the same content.
    """
    skill_path = _skill_path(cwd)

    if skill_path.exists():
        existing = skill_path.read_text()
        if existing == SKILL_CONTENT:
            logger.debug("Skill already installed at %s", skill_path)
            return False

    skill_path.parent.mkdir(parents=True, exist_ok=True)
    skill_path.write_text(SKILL_CONTENT)
    logger.info("Installed messaging skill at %s", skill_path)
    return True


def ensure_skill_installed(cwd: str | Path) -> bool:
    """Check if skill exists for the given cwd, install if missing or outdated.

    Returns True if installed/updated, False if already up-to-date.
    """
    cwd_path = Path(cwd)
    if not cwd_path.is_dir():
        logger.warning("Cannot install skill: cwd %s is not a directory", cwd_path)
        return False
    return install_skill(cwd_path)
