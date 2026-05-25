"""Click-based CLI for ccgram.

Defines the top-level command group and the ``run`` subcommand with all
bot-configuration flags.  Precedence: CLI flag > env var > .env > default.
``apply_args_to_env()`` sets os.environ for explicitly provided flags so
Config reads the overridden values.

Every subcommand body lazy-loads its workers (``run_bot``, ``hook_main``,
``status_main``, ``msg_group``, ``doctor_main``).  ``ccgram --help`` and
``ccgram --version`` stay snappy and avoid pulling PTB / aiohttp /
provider chains; only the invoked subcommand pays its import cost.
"""

import os
import re
import subprocess
from pathlib import Path

import click

_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")
_DEFAULT_IMPORT_ENV_NAMES = (
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "OPENAI_ORG_ID",
    "OPENAI_ORGANIZATION",
    "CODEX_API_KEY",
    "CODEX_BASE_URL",
)
_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _validate_positive_float(
    _ctx: click.Context, _param: click.Parameter, value: float | None
) -> float | None:
    if value is not None and value <= 0:
        raise click.BadParameter("must be positive")
    return value


def _validate_non_negative_int(
    _ctx: click.Context, _param: click.Parameter, value: int | None
) -> int | None:
    if value is not None and value < 0:
        raise click.BadParameter("must be non-negative")
    return value


class _DefaultToRun(click.Group):
    """Click group that runs the ``run`` command when invoked without a subcommand."""

    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        # If the first arg is not a known command and not --help/--version,
        # prepend "run" so flags like -v go to the run command.
        if args and args[0] not in self.commands and not args[0].startswith("--"):
            args = ["run", *args]
        return super().parse_args(ctx, args)


@click.group(
    cls=_DefaultToRun,
    invoke_without_command=True,
    help="Command & Control Bot — manage AI coding agents from Telegram via tmux.",
)
@click.version_option(package_name="ccgram", prog_name="ccgram")
@click.pass_context
def cli(ctx: click.Context) -> None:
    if ctx.invoked_subcommand is None:
        ctx.invoke(run_cmd)


# --- run command -----------------------------------------------------------

# Mapping: click option name → environment variable name
_FLAG_TO_ENV: list[tuple[str, str]] = [
    ("config_dir", "CCGRAM_DIR"),
    ("allowed_users", "ALLOWED_USERS"),
    ("tmux_session", "TMUX_SESSION_NAME"),
    ("monitor_interval", "MONITOR_POLL_INTERVAL"),
    ("group_id", "CCGRAM_GROUP_ID"),
    ("instance_name", "CCGRAM_INSTANCE_NAME"),
    ("autoclose_done", "AUTOCLOSE_DONE_MINUTES"),
    ("autoclose_dead", "AUTOCLOSE_DEAD_MINUTES"),
    ("provider", "CCGRAM_PROVIDER"),
    ("show_hidden_dirs", "CCGRAM_SHOW_HIDDEN_DIRS"),
    ("claude_config_dir", "CLAUDE_CONFIG_DIR"),
    ("whisper_provider", "CCGRAM_WHISPER_PROVIDER"),
    ("ack_reaction", "CCGRAM_ACK_REACTION"),
    ("hide_tool_calls", "CCGRAM_HIDE_TOOL_CALLS"),
    ("status_mode", "CCGRAM_STATUS_MODE"),
]


def apply_args_to_env(**kwargs: object) -> None:
    """Set environment variables from explicitly provided CLI flags.

    Call BEFORE Config instantiation to ensure CLI flags take precedence.
    Only sets env vars for flags that were explicitly provided (not None).
    """
    verbose = kwargs.get("verbose", False)
    log_level = kwargs.get("log_level")

    if verbose:
        os.environ["CCGRAM_LOG_LEVEL"] = "DEBUG"
    elif log_level is not None:
        os.environ["CCGRAM_LOG_LEVEL"] = str(log_level).upper()

    for attr, env_var in _FLAG_TO_ENV:
        value = kwargs.get(attr)
        if value is None:
            continue
        if isinstance(value, Path):
            os.environ[env_var] = str(value.expanduser().resolve())
        else:
            os.environ[env_var] = str(value)


@cli.command("run")
@click.option("-v", "--verbose", is_flag=True, help="Enable debug logging.")
@click.option(
    "--log-level",
    type=click.Choice(_LOG_LEVELS, case_sensitive=False),
    default=None,
    help="Logging level.",
)
@click.option(
    "--config-dir",
    type=click.Path(path_type=Path),
    default=None,
    envvar="CCGRAM_DIR",
    help="Config directory (default: ~/.ccgram).",
)
@click.option(
    "--allowed-users",
    default=None,
    envvar="ALLOWED_USERS",
    help="Comma-separated Telegram user IDs.",
)
@click.option(
    "--tmux-session",
    default=None,
    envvar="TMUX_SESSION_NAME",
    help="Tmux session name (default: ccgram).",
)
@click.option(
    "--monitor-interval",
    type=float,
    default=None,
    callback=_validate_positive_float,
    envvar="MONITOR_POLL_INTERVAL",
    help="Poll interval in seconds (default: 2.0).",
)
@click.option(
    "--group-id",
    type=int,
    default=None,
    envvar="CCGRAM_GROUP_ID",
    help="Restrict to one Telegram group.",
)
@click.option(
    "--instance-name",
    default=None,
    envvar="CCGRAM_INSTANCE_NAME",
    help="Display label for multi-instance.",
)
@click.option(
    "--autoclose-done",
    type=int,
    default=None,
    callback=_validate_non_negative_int,
    envvar="AUTOCLOSE_DONE_MINUTES",
    help="Auto-close done topics after N minutes (default: 30, 0=disabled).",
)
@click.option(
    "--autoclose-dead",
    type=int,
    default=None,
    callback=_validate_non_negative_int,
    envvar="AUTOCLOSE_DEAD_MINUTES",
    help="Auto-close dead sessions after N minutes (default: 10, 0=disabled).",
)
@click.option(
    "--provider",
    default=None,
    envvar="CCGRAM_PROVIDER",
    help="Agent provider name (default: claude).",
)
@click.option(
    "--show-hidden-dirs",
    is_flag=True,
    default=None,
    envvar="CCGRAM_SHOW_HIDDEN_DIRS",
    help="Show hidden (dot) directories in directory browser.",
)
@click.option(
    "--claude-config-dir",
    type=click.Path(path_type=Path),
    default=None,
    envvar="CLAUDE_CONFIG_DIR",
    help="Claude config directory (default: ~/.claude).",
)
@click.option(
    "--whisper-provider",
    default=None,
    envvar="CCGRAM_WHISPER_PROVIDER",
    help='Whisper transcription provider: "openai", "groq", or "" (disabled).',
)
@click.option(
    "--ack-reaction",
    default=None,
    envvar="CCGRAM_ACK_REACTION",
    help='React to forwarded messages with emoji (e.g., "👀"). Empty=disabled.',
)
@click.option(
    "--hide-tool-calls",
    is_flag=True,
    default=None,
    envvar="CCGRAM_HIDE_TOOL_CALLS",
    help="Hide tool_use/tool_result messages globally (per-window override via /toolcalls).",
)
@click.option(
    "--status-mode",
    type=click.Choice(["system", "user"], case_sensitive=False),
    default=None,
    envvar="CCGRAM_STATUS_MODE",
    help="Topic emoji color scheme: 'system' (green=active) or 'user' (green=ready for me).",
)
def run_cmd(**kwargs: object) -> None:
    """Start the bot with optional overrides."""
    apply_args_to_env(**kwargs)

    # Lazy: defer subcommand import until that command is invoked, keeping `ccgram --help` fast
    from .main import run_bot

    run_bot()


# --- hook command ----------------------------------------------------------


@cli.command("hook")
@click.option(
    "--install", is_flag=True, help="Install hook into ~/.claude/settings.json."
)
@click.option(
    "--uninstall", is_flag=True, help="Remove hook from ~/.claude/settings.json."
)
@click.option("--status", is_flag=True, help="Check if hook is installed.")
def hook_cmd(install: bool, uninstall: bool, status: bool) -> None:
    """Claude Code session tracking hook."""
    # Lazy: defer subcommand import until that command is invoked, keeping `ccgram --help` fast
    from .hook import hook_main

    hook_main(install=install, uninstall=uninstall, status=status)


# --- status command --------------------------------------------------------


@cli.command("status")
def status_cmd() -> None:
    """Show running state."""
    # Lazy: defer subcommand import until that command is invoked, keeping `ccgram --help` fast
    from .status_cmd import status_main

    status_main()


# --- import-env command ---------------------------------------------------


def _tmux_quote(value: str) -> str:
    """Single-quote *value* for a tmux source-file command."""
    return "'" + value.replace("'", "'\\''") + "'"


@cli.command("import-env")
@click.argument("names", nargs=-1)
@click.option(
    "--tmux-session",
    default=None,
    envvar="TMUX_SESSION_NAME",
    help="Tmux session name (default: ccgram).",
)
@click.option(
    "--unset-missing",
    is_flag=True,
    help="Unset variables that are not present in the current shell.",
)
def import_env_cmd(
    names: tuple[str, ...], tmux_session: str | None, unset_missing: bool
) -> None:
    """Import current-shell API env vars into ccgram's tmux session."""
    session = tmux_session or os.environ.get("TMUX_SESSION_NAME", "ccgram")
    selected = names or _DEFAULT_IMPORT_ENV_NAMES

    commands: list[str] = []
    imported: list[str] = []
    unset: list[str] = []
    missing: list[str] = []
    for name in selected:
        if not name:
            continue
        if not _ENV_NAME_RE.match(name):
            raise click.BadParameter(f"invalid environment variable name: {name}")
        if name in os.environ:
            commands.append(
                f"set-environment -t {_tmux_quote(session)} {name} "
                f"{_tmux_quote(os.environ[name])}"
            )
            imported.append(name)
        elif unset_missing:
            commands.append(f"set-environment -t {_tmux_quote(session)} -u {name}")
            unset.append(name)
        else:
            missing.append(name)

    if not commands:
        click.echo("No environment variables imported.")
        if missing:
            click.echo(f"Missing in current shell: {', '.join(missing)}")
        return

    proc = subprocess.run(
        ["tmux", "source-file", "-"],
        input="\n".join(commands) + "\n",
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise click.ClickException(proc.stderr.strip() or "tmux source-file failed")

    if imported:
        click.echo(f"Imported into tmux session {session}: {', '.join(imported)}")
    if unset:
        click.echo(f"Unset in tmux session {session}: {', '.join(unset)}")
    if missing:
        click.echo(f"Skipped missing vars: {', '.join(missing)}")


# --- doctor command --------------------------------------------------------


# --- msg command group -----------------------------------------------------


def _register_msg_group() -> None:
    # Lazy: defer subcommand import until that command is invoked, keeping `ccgram --help` fast
    from .msg_cmd import msg_group

    cli.add_command(msg_group, "msg")


_register_msg_group()


# --- doctor command --------------------------------------------------------


@cli.command("doctor")
@click.option("--fix", is_flag=True, help="Auto-fix issues where possible.")
def doctor_cmd(fix: bool) -> None:
    """Validate setup and diagnose issues."""
    # Lazy: defer subcommand import until that command is invoked, keeping `ccgram --help` fast
    from .doctor_cmd import doctor_main

    doctor_main(fix=fix)
