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

    def test_other_topic_message_does_not_clear_pending_directory_browser(self):
        import asyncio
        import importlib
        from unittest.mock import AsyncMock, patch

        text_handler = importlib.import_module("ccgram.handlers.text.text_handler")
        directory_browser = importlib.import_module(
            "ccgram.handlers.topics.directory_browser"
        )
        user_state = importlib.import_module("ccgram.handlers.user_state")

        user_data = {
            directory_browser.STATE_KEY: directory_browser.STATE_BROWSING_DIRECTORY,
            directory_browser.BROWSE_PATH_KEY: "/mnt/nvme",
            directory_browser.BROWSE_PAGE_KEY: 0,
            directory_browser.BROWSE_DIRS_KEY: [],
            user_state.PENDING_THREAD_ID: 243,
            user_state.PENDING_THREAD_TEXT: "在么",
        }
        message = object()

        async def run():
            with patch.object(text_handler, "safe_reply", new=AsyncMock()) as reply_mock:
                handled = await text_handler._check_ui_guards(
                    user_data, 208, message
                )
                self.assertFalse(handled)
                reply_mock.assert_not_awaited()

        asyncio.run(run())
        self.assertEqual(user_data.get(user_state.PENDING_THREAD_ID), 243)
        self.assertEqual(user_data.get(user_state.PENDING_THREAD_TEXT), "在么")
        self.assertEqual(
            user_data.get(directory_browser.STATE_KEY),
            directory_browser.STATE_BROWSING_DIRECTORY,
        )
        self.assertEqual(user_data.get(directory_browser.BROWSE_PATH_KEY), "/mnt/nvme")


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


    def test_tick_window_rechecks_live_tmux_window_before_dead_notification(self):
        import asyncio
        import importlib
        import types
        from unittest.mock import AsyncMock, Mock, patch

        window_tick = importlib.import_module("ccgram.handlers.polling.window_tick")
        live_window = types.SimpleNamespace(
            window_id="@11",
            window_name="nvme-3",
            cwd="/mnt/nvme",
            pane_current_command="node",
            pane_tty="/dev/pts/345",
        )

        async def run():
            with (
                patch.object(
                    window_tick.lifecycle_strategy,
                    "is_dead_notified",
                    return_value=False,
                ),
                patch.object(window_tick, "PTBTelegramClient", return_value=object()),
                patch(
                    "ccgram.tmux_manager.tmux_manager.find_window_by_id",
                    new=AsyncMock(return_value=live_window),
                ) as find_mock,
                patch.object(
                    window_tick,
                    "_handle_dead_window_notification",
                    new=AsyncMock(),
                ) as dead_mock,
                patch.object(
                    window_tick,
                    "discover_and_register_transcript",
                    new=AsyncMock(),
                ) as discover_mock,
                patch.object(window_tick, "get_message_queue", return_value=None),
                patch.object(window_tick, "_update_status", new=AsyncMock()) as update_mock,
                patch.object(window_tick, "_scan_window_panes", new=AsyncMock()),
                patch.object(window_tick, "_maybe_check_passive_shell", new=AsyncMock()),
            ):
                await window_tick.tick_window(object(), 1, 295, "@11", None)
                find_mock.assert_awaited_once_with("@11")
                dead_mock.assert_not_awaited()
                discover_mock.assert_awaited_once()
                update_mock.assert_awaited_once()

        asyncio.run(run())

    def test_tick_window_clears_false_dead_notification_when_window_is_live(self):
        import asyncio
        import importlib
        import types
        from unittest.mock import AsyncMock, Mock, patch

        window_tick = importlib.import_module("ccgram.handlers.polling.window_tick")
        live_window = types.SimpleNamespace(
            window_id="@11",
            window_name="nvme-3",
            cwd="/mnt/nvme",
            pane_current_command="node",
            pane_tty="/dev/pts/345",
        )

        async def run():
            with (
                patch.object(
                    window_tick.lifecycle_strategy,
                    "is_dead_notified",
                    return_value=True,
                ),
                patch.object(
                    window_tick.lifecycle_strategy,
                    "clear_dead_notification",
                    new=Mock(),
                ) as clear_dead_mock,
                patch.object(
                    window_tick.lifecycle_strategy,
                    "clear_autoclose_timer",
                    new=Mock(),
                ) as clear_timer_mock,
                patch.object(window_tick, "PTBTelegramClient", return_value=object()),
                patch(
                    "ccgram.tmux_manager.tmux_manager.find_window_by_id",
                    new=AsyncMock(return_value=live_window),
                ),
                patch.object(
                    window_tick,
                    "_handle_dead_window_notification",
                    new=AsyncMock(),
                ) as dead_mock,
                patch.object(
                    window_tick,
                    "discover_and_register_transcript",
                    new=AsyncMock(),
                ) as discover_mock,
                patch.object(window_tick, "get_message_queue", return_value=None),
                patch.object(window_tick, "_update_status", new=AsyncMock()) as update_mock,
                patch.object(window_tick, "_scan_window_panes", new=AsyncMock()),
                patch.object(window_tick, "_maybe_check_passive_shell", new=AsyncMock()),
            ):
                await window_tick.tick_window(object(), 1, 295, "@11", None)
                clear_dead_mock.assert_called_once_with(1, 295)
                clear_timer_mock.assert_called_once_with(1, 295)
                dead_mock.assert_not_awaited()
                discover_mock.assert_awaited_once()
                update_mock.assert_awaited_once()

        asyncio.run(run())


    def test_draft_stream_thread_not_found_is_not_transient(self):
        import asyncio
        from unittest.mock import AsyncMock, patch

        from telegram.error import BadRequest

        from ccgram.telegram_draft import DraftStream

        async def run():
            bot = AsyncMock()
            bot.do_api_request.side_effect = BadRequest("Message thread not found")

            stream = DraftStream(bot, -100, message_thread_id=307)

            with patch("ccgram.telegram_draft.logger.warning") as warn_mock:
                msg_id = await stream.start("working")

            self.assertIsNone(msg_id)
            bot.do_api_request.assert_awaited_once()
            bot.send_message.assert_not_awaited()
            warning_text = "\n".join(str(call) for call in warn_mock.call_args_list)
            self.assertIn("permanent failure", warning_text)
            self.assertIn("thread=%s", warning_text)

        asyncio.run(run())


    def test_draft_stream_records_permanent_thread_failure(self):
        import asyncio
        from unittest.mock import AsyncMock

        from telegram.error import BadRequest

        from ccgram.telegram_draft import (
            DraftStream,
            pop_permanent_thread_failure,
        )

        async def run():
            bot = AsyncMock()
            bot.do_api_request.side_effect = BadRequest("Message thread not found")

            stream = DraftStream(bot, -100, message_thread_id=307)
            msg_id = await stream.start("working")

            self.assertIsNone(msg_id)
            self.assertEqual(
                pop_permanent_thread_failure(-100, 307), "Message thread not found"
            )
            self.assertIsNone(pop_permanent_thread_failure(-100, 307))

        asyncio.run(run())


    def test_session_map_prune_keeps_live_unbound_window_state_without_hook_entry(self):
        from unittest.mock import Mock

        from ccgram.session_map import SessionMapSync
        from ccgram.thread_router import ThreadRouter, get_thread_router, install_thread_router
        from ccgram.tmux_manager import TmuxWindow
        from ccgram.window_state_store import (
            CCGRAM_CREATED_WINDOW_ORIGIN,
            WindowStateStore,
            get_window_store,
            install_window_store,
        )

        try:
            previous_store = get_window_store()
        except RuntimeError:
            previous_store = None
        try:
            previous_router = get_thread_router()
        except RuntimeError:
            previous_router = None
        store = WindowStateStore(
            schedule_save=Mock(),
            on_hookless_provider_switch=Mock(),
        )
        router = ThreadRouter(schedule_save=Mock(), has_window_state=Mock(return_value=True))
        install_window_store(store)
        install_thread_router(router)
        try:
            state = store.get_window_state("@11")
            state.cwd = "/mnt/nvme"
            state.provider_name = "codex"
            state.origin = CCGRAM_CREATED_WINDOW_ORIGIN
            live_windows = [TmuxWindow(window_id="@11", window_name="nvme-3", cwd="/mnt/nvme")]

            removed = SessionMapSync(schedule_save=Mock())._remove_stale_window_states(
                valid_wids=set(),
                old_format_sids=set(),
                live_windows=live_windows,
            )

            self.assertFalse(removed)
            self.assertTrue(store.has_window("@11"))
            self.assertEqual(store.get_window_state("@11").origin, CCGRAM_CREATED_WINDOW_ORIGIN)
        finally:
            if previous_store is not None:
                install_window_store(previous_store)
            if previous_router is not None:
                install_thread_router(previous_router)


    def test_session_map_sync_preserves_origin_when_codex_hook_arrives(self):
        from unittest.mock import Mock

        from ccgram.session_map import SessionMapSync
        from ccgram.thread_router import ThreadRouter, get_thread_router, install_thread_router
        from ccgram.window_state_store import (
            CCGRAM_CREATED_WINDOW_ORIGIN,
            WindowStateStore,
            get_window_store,
            install_window_store,
        )

        try:
            previous_store = get_window_store()
        except RuntimeError:
            previous_store = None
        try:
            previous_router = get_thread_router()
        except RuntimeError:
            previous_router = None
        store = WindowStateStore(
            schedule_save=Mock(),
            on_hookless_provider_switch=Mock(),
        )
        install_window_store(store)
        router = ThreadRouter(schedule_save=Mock(), has_window_state=Mock(return_value=True))
        install_thread_router(router)
        try:
            state = store.get_window_state("@11")
            state.origin = CCGRAM_CREATED_WINDOW_ORIGIN
            sync = SessionMapSync(schedule_save=Mock())

            changed = sync._sync_window_from_session_map(
                "@11",
                {
                    "session_id": "sid-11",
                    "cwd": "/mnt/nvme",
                    "window_name": "nvme-3",
                    "transcript_path": "/tmp/transcript.jsonl",
                    "provider_name": "codex",
                },
            )

            self.assertTrue(changed)
            self.assertEqual(store.get_window_state("@11").origin, CCGRAM_CREATED_WINDOW_ORIGIN)
        finally:
            if previous_store is not None:
                install_window_store(previous_store)
            if previous_router is not None:
                install_thread_router(previous_router)


    def test_autoclose_kills_ccgram_created_window_to_prevent_recreated_topic(self):
        import asyncio
        import importlib
        import types
        from unittest.mock import AsyncMock, Mock, patch

        topic_lifecycle = importlib.import_module("ccgram.handlers.topics.topic_lifecycle")
        thread_router_mod = importlib.import_module("ccgram.thread_router")

        async def run():
            router = thread_router_mod.ThreadRouter(
                schedule_save=Mock(),
                has_window_state=Mock(return_value=True),
            )
            router.bind_thread(1, 295, "@11")
            router.set_group_chat_id(1, 295, -100)
            thread_router_mod.install_thread_router(router)
            client = AsyncMock()
            window_view = types.SimpleNamespace(origin="ccgram_created")

            with (
                patch("ccgram.window_query.view_window", return_value=window_view),
                patch(
                    "ccgram.tmux_manager.tmux_manager.find_window_by_id",
                    new=AsyncMock(return_value=object()),
                ),
                patch(
                    "ccgram.tmux_manager.tmux_manager.kill_window",
                    new=AsyncMock(return_value=True),
                ) as kill_mock,
                patch.object(
                    topic_lifecycle,
                    "clear_topic_state",
                    new=AsyncMock(),
                ) as clear_mock,
            ):
                await topic_lifecycle._close_expired_topic(client, 1, 295)

            client.delete_forum_topic.assert_awaited_once_with(
                chat_id=-100,
                message_thread_id=295,
            )
            kill_mock.assert_awaited_once_with("@11")
            clear_mock.assert_awaited_once()
            self.assertTrue(clear_mock.await_args.kwargs["window_dead"])
            self.assertIsNone(router.get_window_for_thread(1, 295))

        asyncio.run(run())


    def test_status_thread_not_found_kills_ccgram_created_window(self):
        import asyncio
        import importlib
        import types
        from unittest.mock import AsyncMock, Mock, patch

        status_bubble = importlib.import_module(
            "ccgram.handlers.status.status_bubble"
        )
        message_queue = importlib.import_module(
            "ccgram.handlers.messaging_pipeline.message_queue"
        )
        thread_router_mod = importlib.import_module("ccgram.thread_router")

        async def run():
            client = object()
            router = thread_router_mod.ThreadRouter(
                schedule_save=Mock(),
                has_window_state=Mock(return_value=True),
            )
            router.bind_thread(1, 307, "@11")
            router.set_group_chat_id(1, 307, -100)
            thread_router_mod.install_thread_router(router)
            window_view = types.SimpleNamespace(origin="ccgram_created")

            with (
                patch.object(status_bubble, "_rc_active_fn", lambda _window_id: False),
                patch.object(
                    status_bubble, "_start_bubble", new=AsyncMock(return_value=None)
                ),
                patch.object(
                    message_queue,
                    "pop_permanent_thread_failure",
                    Mock(return_value="Message thread not found"),
                ),
                patch("ccgram.window_query.view_window", return_value=window_view),
                patch(
                    "ccgram.tmux_manager.tmux_manager.find_window_by_id",
                    new=AsyncMock(return_value=object()),
                ),
                patch(
                    "ccgram.handlers.cleanup.clear_topic_state",
                    new=AsyncMock(),
                ) as clear_mock,
                patch(
                    "ccgram.tmux_manager.tmux_manager.kill_window",
                    new=AsyncMock(return_value=True),
                ) as kill_mock,
            ):
                task = message_queue.StatusUpdateTask("@11", "working", thread_id=307)
                await message_queue._dispatch(
                    client, 1, task, asyncio.Queue(), asyncio.Lock()
                )

            self.assertIsNone(router.get_window_for_thread(1, 307))
            self.assertEqual(router.get_thread_for_window(1, "@11"), None)
            clear_mock.assert_awaited_once()
            self.assertIsNone(clear_mock.await_args.kwargs["client"])
            self.assertEqual(clear_mock.await_args.kwargs["window_id"], "@11")
            self.assertTrue(clear_mock.await_args.kwargs["window_dead"])
            kill_mock.assert_awaited_once_with("@11")

        asyncio.run(run())

    def test_status_thread_not_found_keeps_manual_window(self):
        import asyncio
        import importlib
        import types
        from unittest.mock import AsyncMock, Mock, patch

        status_bubble = importlib.import_module(
            "ccgram.handlers.status.status_bubble"
        )
        message_queue = importlib.import_module(
            "ccgram.handlers.messaging_pipeline.message_queue"
        )
        thread_router_mod = importlib.import_module("ccgram.thread_router")

        async def run():
            client = object()
            router = thread_router_mod.ThreadRouter(
                schedule_save=Mock(),
                has_window_state=Mock(return_value=True),
            )
            router.bind_thread(1, 307, "@11")
            router.set_group_chat_id(1, 307, -100)
            thread_router_mod.install_thread_router(router)
            window_view = types.SimpleNamespace(origin="manual_discovered")

            with (
                patch.object(status_bubble, "_rc_active_fn", lambda _window_id: False),
                patch.object(
                    status_bubble, "_start_bubble", new=AsyncMock(return_value=None)
                ),
                patch.object(
                    message_queue,
                    "pop_permanent_thread_failure",
                    Mock(return_value="Message thread not found"),
                ),
                patch("ccgram.window_query.view_window", return_value=window_view),
                patch(
                    "ccgram.tmux_manager.tmux_manager.find_window_by_id",
                    new=AsyncMock(return_value=object()),
                ),
                patch(
                    "ccgram.handlers.cleanup.clear_topic_state",
                    new=AsyncMock(),
                ) as clear_mock,
                patch(
                    "ccgram.tmux_manager.tmux_manager.kill_window",
                    new=AsyncMock(return_value=True),
                ) as kill_mock,
            ):
                task = message_queue.StatusUpdateTask("@11", "working", thread_id=307)
                await message_queue._dispatch(
                    client, 1, task, asyncio.Queue(), asyncio.Lock()
                )

            self.assertIsNone(router.get_window_for_thread(1, 307))
            self.assertEqual(router.get_thread_for_window(1, "@11"), None)
            clear_mock.assert_awaited_once()
            self.assertIsNone(clear_mock.await_args.kwargs["client"])
            self.assertEqual(clear_mock.await_args.kwargs["window_id"], "@11")
            self.assertFalse(clear_mock.await_args.kwargs["window_dead"])
            kill_mock.assert_not_awaited()

        asyncio.run(run())


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
