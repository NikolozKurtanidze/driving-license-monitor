import io
import json
import logging
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

import monitor


class MonitorTests(unittest.TestCase):
    @patch("monitor.send_discord")
    @patch("monitor.fetch_dates", side_effect=[[], ["date"]])
    @patch("monitor.load_webhook", side_effect=["alerts-webhook", "logs-webhook"])
    @patch("sys.argv", ["monitor.py", "--once"])
    def test_separate_channel_receives_empty_and_nonempty_check_logs(self, load, fetch, send):
        previous_level = monitor.LOG.level
        monitor.LOG.setLevel(logging.INFO)
        try:
            self.assertEqual(monitor.main(), 0)
        finally:
            monitor.LOG.setLevel(previous_level)
        self.assertEqual(send.call_count, 2)
        self.assertEqual(send.call_args_list[0].args[0], "alerts-webhook")
        destination, content = send.call_args_list[1].args
        self.assertEqual(destination, "logs-webhook")
        self.assertIn("Center 15: 0", content)
        self.assertIn("Center 7: 1", content)
        self.assertIn("Discord notification sent", content)

    @patch("monitor.send_discord", side_effect=HTTPError("secret-token", 429, "", {}, None))
    def test_log_delivery_failure_is_local_and_does_not_raise_or_recurse(self, send):
        handler = monitor.DiscordLogHandler("logs-webhook")
        record = logging.LogRecord("exam-monitor", logging.ERROR, "", 0, "Check failed", (), None)
        handler.emit(record)
        with patch("sys.stderr", new_callable=io.StringIO) as output:
            handler.flush()
        self.assertIn("HTTP 429", output.getvalue())
        self.assertNotIn("secret-token", output.getvalue())
        handler.flush()
        send.assert_called_once()
        self.assertIn("Check failed", send.call_args.args[1])

    @patch.dict("os.environ", {"DISCORD_LOG_WEBHOOK_URL": "https://discord.com/api/webhooks/123/log-token"})
    def test_second_webhook_loads_from_environment(self):
        self.assertEqual(monitor.load_webhook("DISCORD_LOG_WEBHOOK_URL", required=False),
                         "https://discord.com/api/webhooks/123/log-token")

    @patch.dict("os.environ", {}, clear=True)
    @patch("monitor.Path.exists", return_value=False)
    def test_log_webhook_is_optional(self, exists):
        self.assertIsNone(monitor.load_webhook("DISCORD_LOG_WEBHOOK_URL", required=False))

    @patch("monitor.send_discord")
    @patch("monitor.fetch_dates", side_effect=[[], []])
    def test_empty_arrays_are_silent(self, fetch, send):
        self.assertTrue(monitor.check_once("unused"))
        self.assertEqual(fetch.call_count, 2)
        send.assert_not_called()

    @patch("monitor.send_discord")
    @patch("monitor.fetch_dates", return_value=["2026-10-01"])
    def test_nonempty_arrays_notify_every_cycle(self, fetch, send):
        monitor.check_once("unused")
        monitor.check_once("unused")
        self.assertEqual(send.call_count, 4)
        self.assertIn("Center 15", send.call_args_list[0].args[1])
        self.assertIn("Center 7", send.call_args_list[1].args[1])

    @patch("monitor.send_discord")
    @patch("monitor.fetch_dates", side_effect=[ValueError("bad response"), ["date"]])
    def test_one_bad_endpoint_does_not_block_other(self, fetch, send):
        with self.assertLogs("exam-monitor", level="ERROR"):
            self.assertFalse(monitor.check_once("unused"))
        send.assert_called_once()

    @patch("monitor.send_discord", side_effect=[HTTPError("secret", 429, "", {}, None), None])
    @patch("monitor.fetch_dates", return_value=["date"])
    def test_discord_failure_does_not_block_other_center_or_leak_url(self, fetch, send):
        with self.assertLogs("exam-monitor", level="ERROR") as logs:
            self.assertFalse(monitor.check_once("unused"))
        self.assertEqual(send.call_count, 2)
        self.assertNotIn("secret", "".join(logs.output))

    def test_rejects_invalid_json_and_nonarray_responses(self):
        for body in (b"<html>error</html>", b'{}', b'null', b'"hello"'):
            with self.subTest(body=body), patch("monitor.urlopen", return_value=io.BytesIO(body)):
                with self.assertRaises(ValueError):
                    monitor.fetch_dates(monitor.ENDPOINTS[15])

    def test_message_fits_discord_limit(self):
        message = monitor.availability_message(15, monitor.ENDPOINTS[15], ["x" * 10000])
        self.assertLessEqual(len(message), 2000)
        self.assertIn("truncated", message)

    @patch("monitor.urlopen", return_value=io.BytesIO(b'{}'))
    def test_discord_post_confirms_delivery_and_disables_mentions(self, urlopen):
        monitor.send_discord("https://discord.com/api/webhooks/123/token", "hello")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.method, "POST")
        self.assertIn("wait=true", request.full_url)
        self.assertEqual(json.loads(request.data)["allowed_mentions"], {"parse": []})
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 30)


if __name__ == "__main__":
    unittest.main()
