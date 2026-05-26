import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class LaunchDefaultsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.TemporaryDirectory()
        cls._env = patch.dict(
            os.environ,
            {
                "CCGRAM_DIR": str(Path(cls._tmpdir.name) / ".ccgram"),
                "TELEGRAM_BOT_TOKEN": "dummy-token",
                "ALLOWED_USERS": "1",
            },
        )
        cls._env.start()

    @classmethod
    def tearDownClass(cls):
        cls._env.stop()
        cls._tmpdir.cleanup()

    def test_resolve_default_workdir_prefers_configured_directory(self):
        from ccgram.config import config
        from ccgram.handlers.topics.directory_browser import resolve_default_workdir

        with tempfile.TemporaryDirectory() as tmp:
            config.default_workdir = tmp
            self.assertEqual(resolve_default_workdir(), str(Path(tmp).resolve()))

    def test_codex_launch_detection_accepts_path_and_flags(self):
        from ccgram.tmux_manager import _is_codex_launch_command

        self.assertTrue(
            _is_codex_launch_command(
                "codex --dangerously-bypass-approvals-and-sandbox"
            )
        )
        self.assertTrue(_is_codex_launch_command("/usr/local/bin/codex"))
        self.assertTrue(_is_codex_launch_command("env FOO=bar /usr/local/bin/codex"))
        self.assertFalse(_is_codex_launch_command("claude"))

    def test_codex_launch_sequence_unsets_proxy(self):
        from ccgram.tmux_manager import TmuxManager

        self.assertEqual(
            TmuxManager._build_agent_launch_sequence("codex", "--yolo"),
            [
                "unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy",
                "codex --yolo",
            ],
        )
        self.assertEqual(
            TmuxManager._build_agent_launch_sequence("claude", ""), ["claude"]
        )

    def test_existing_shell_window_pending_text_is_not_raw_executed(self):
        import asyncio
        import importlib
        import types
        from unittest.mock import AsyncMock, patch

        window_callbacks = importlib.import_module(
            "ccgram.handlers.topics.window_callbacks"
        )

        class Caps:
            chat_first_command_path = True

        provider = types.SimpleNamespace(capabilities=Caps())
        client = object()

        async def run():
            with (
                patch("ccgram.providers.get_provider_for_window", return_value=provider),
                patch.object(
                    window_callbacks, "send_to_window", new=AsyncMock()
                ) as send_mock,
                patch.object(
                    window_callbacks.thread_router,
                    "resolve_chat_id",
                    return_value=-100,
                ),
                patch.object(
                    window_callbacks,
                    "safe_send",
                    new=AsyncMock(),
                ) as safe_send_mock,
            ):
                await window_callbacks._forward_pending_text(
                    client,
                    1,
                    2,
                    "@1",
                    "在么",
                    "shell",
                    is_existing_window=True,
                )
                send_mock.assert_not_awaited()
                safe_send_mock.assert_awaited_once()

        asyncio.run(run())

    def test_shell_provider_requires_bang_when_llm_not_configured(self):
        import asyncio
        import importlib
        from unittest.mock import AsyncMock, Mock, patch

        shell_commands = importlib.import_module("ccgram.handlers.shell.shell_commands")
        client = object()

        async def run():
            with (
                patch.object(
                    shell_commands, "enqueue_status_update", new=AsyncMock()
                ),
                patch.object(
                    shell_commands.lifecycle_strategy,
                    "clear_probe_failures",
                    new=Mock(),
                ),
                patch.object(
                    shell_commands, "_ensure_prompt_marker", new=AsyncMock()
                ),
                patch.object(shell_commands, "_send_typing", new=AsyncMock()),
                patch.object(shell_commands, "react", new=AsyncMock()),
                patch.object(
                    shell_commands.thread_router, "resolve_chat_id", return_value=-100
                ),
                patch.object(shell_commands, "get_completer", return_value=None),
                patch.object(
                    shell_commands, "_execute_raw_command", new=AsyncMock()
                ) as exec_mock,
                patch.object(
                    shell_commands, "safe_send", new=AsyncMock()
                ) as safe_send_mock,
            ):
                await shell_commands.handle_shell_message(
                    client,
                    1,
                    2,
                    "@1",
                    "在么",
                    None,
                )
                exec_mock.assert_not_awaited()
                safe_send_mock.assert_awaited_once()

        asyncio.run(run())

    def test_live_shell_pane_overrides_stale_codex_state(self):
        import asyncio
        import importlib
        import types
        from unittest.mock import AsyncMock, Mock, patch

        text_handler = importlib.import_module("ccgram.handlers.text.text_handler")
        shell_commands = importlib.import_module("ccgram.handlers.shell.shell_commands")

        class Caps:
            supports_mailbox_delivery = True

        codex_provider = types.SimpleNamespace(capabilities=Caps())
        shell_provider = types.SimpleNamespace(
            capabilities=types.SimpleNamespace(supports_mailbox_delivery=False)
        )

        class Chat:
            id = -100
            type = "supergroup"

        message = types.SimpleNamespace(text="在么", chat=Chat(), message_id=10)
        update = types.SimpleNamespace(
            effective_user=types.SimpleNamespace(id=1),
            message=message,
        )
        context = types.SimpleNamespace(user_data={}, bot=object())
        live_window = types.SimpleNamespace(
            pane_current_command="bash",
            pane_tty="/dev/pts/1",
            cwd="/mnt/nvme",
        )

        async def run():
            with (
                patch.object(text_handler, "_get_thread_id", return_value=2),
                patch.object(text_handler, "sync_scoped_menu_for_text_context", new=AsyncMock()),
                patch.object(text_handler, "apply_pane_rename", new=AsyncMock(return_value=False)),
                patch.object(
                    text_handler.thread_router,
                    "set_group_chat_id",
                    new=Mock(),
                ),
                patch.object(
                    text_handler.thread_router,
                    "get_window_for_thread",
                    return_value="@1",
                ),
                patch.object(
                    text_handler.tmux_manager,
                    "find_window_by_id",
                    new=AsyncMock(return_value=live_window),
                ),
                patch.object(
                    text_handler.window_query,
                    "get_window_provider",
                    return_value="codex",
                ),
                patch.object(
                    text_handler,
                    "get_provider_for_window",
                    side_effect=lambda _window_id, provider_name=None: (
                        shell_provider if provider_name == "shell" else codex_provider
                    ),
                ),
                patch("ccgram.providers.detect_provider_from_pane", new=AsyncMock(return_value="shell")),
                patch.object(
                    shell_commands,
                    "handle_shell_message",
                    new=AsyncMock(),
                ) as shell_mock,
                patch.object(
                    text_handler,
                    "_forward_message",
                    new=AsyncMock(),
                ) as forward_mock,
            ):
                await text_handler.handle_text_message(update, context)
                shell_mock.assert_awaited_once()
                forward_mock.assert_not_awaited()

        asyncio.run(run())


    def test_codex_live_discovery_uses_pane_tty_open_fd_before_cwd_mtime(self):
        import json
        import os
        from unittest.mock import patch

        from ccgram.providers.codex import CodexProvider

        def write_meta(path, session_id, cwd):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {
                        "type": "session_meta",
                        "payload": {
                            "id": session_id,
                            "cwd": cwd,
                            "originator": "codex-tui",
                            "source": "cli",
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / "home"
            sessions = home / ".codex" / "sessions" / "2026" / "05" / "26"
            actual = sessions / "rollout-actual.jsonl"
            newer_wrong = sessions / "rollout-wrong.jsonl"
            write_meta(actual, "actual-session", "/mnt/nvme")
            write_meta(newer_wrong, "wrong-session", "/mnt/nvme")
            os.utime(actual, (1000, 1000))
            os.utime(newer_wrong, (2000, 2000))

            proc = root / "proc"
            live_pid = proc / "123"
            (live_pid / "fd").mkdir(parents=True)
            (live_pid / "cmdline").write_bytes(b"/usr/local/bin/codex\0--dangerously-bypass-approvals-and-sandbox\0")
            os.symlink("/dev/pts/338", live_pid / "fd" / "0")
            os.symlink(actual, live_pid / "fd" / "60")

            other_pid = proc / "456"
            (other_pid / "fd").mkdir(parents=True)
            (other_pid / "cmdline").write_bytes(b"/usr/local/bin/codex\0resume\0wrong-session\0")
            os.symlink("/dev/pts/999", other_pid / "fd" / "0")
            os.symlink(newer_wrong, other_pid / "fd" / "60")

            with patch("ccgram.providers.codex.Path.home", return_value=home):
                event = CodexProvider().discover_transcript(
                    "/mnt/nvme",
                    "ccgram:@8",
                    max_age=0,
                    pane_tty="/dev/pts/338",
                    proc_root=proc,
                )

            self.assertIsNotNone(event)
            self.assertEqual(event.session_id, "actual-session")
            self.assertEqual(event.transcript_path, str(actual))


    def test_live_transcript_discovery_uses_provider_age_default_not_zero(self):
        import asyncio
        import importlib
        import types
        from unittest.mock import patch

        transcript_discovery = importlib.import_module(
            "ccgram.handlers.recovery.transcript_discovery"
        )

        class Provider:
            capabilities = types.SimpleNamespace(name="codex")

            def __init__(self):
                self.max_age = "unset"

            def discover_transcript(self, cwd, window_key, *, max_age=None, pane_tty=""):
                self.max_age = max_age
                return None

        provider = Provider()
        state = types.SimpleNamespace(cwd="/mnt/nvme", session_id="", transcript_path="", provider_name="codex")

        async def run():
            async def immediate(func, *args, **kwargs):
                return func(*args, **kwargs)

            with (
                patch.object(transcript_discovery, "is_foreign_window", return_value=False),
                patch.object(transcript_discovery.asyncio, "to_thread", new=immediate),
            ):
                await transcript_discovery._find_and_register_transcript(
                    "@8",
                    state,
                    [("codex", provider)],
                    True,
                    pane_tty="/dev/pts/338",
                )

        asyncio.run(run())
        self.assertIsNone(provider.max_age)


if __name__ == "__main__":
    unittest.main()
