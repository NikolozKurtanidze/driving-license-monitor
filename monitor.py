#!/usr/bin/env python3
"""Poll exam availability and post nonempty results to Discord."""

import argparse
import json
import logging
import os
from pathlib import Path
import signal
import sys
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

INTERVAL_SECONDS = 600
TIMEOUT_SECONDS = 30
ENDPOINTS = {
    center: f"https://exam-booking.sa.gov.ge/theory/dates?CategoryCode=1&CenterId={center}"
    for center in (15, 7)
}
LOG = logging.getLogger("exam-monitor")


def load_webhook(setting="DISCORD_WEBHOOK_URL", required=True):
    # Environment takes precedence over settings in the local .env file.
    webhook = os.environ.get(setting, "").strip()
    env_file = Path(__file__).with_name(".env")
    if not webhook and env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.strip().partition("=")
            if sep and key.strip() == setting:
                webhook = value.strip().strip("\"'")
    if not webhook and not required:
        return None
    parts = urlsplit(webhook)
    if (parts.scheme != "https" or parts.hostname != "discord.com"
            or not parts.path.startswith("/api/webhooks/")
            or len(parts.path.rstrip("/").split("/")) != 5):
        raise ValueError(f"Set {setting} to your Discord webhook URL in .env.")
    return webhook


def fetch_dates(url):
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "ExamMonitor/1.0"})
    with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        dates = json.load(response)
    if not isinstance(dates, list):
        raise ValueError("Expected a JSON array from the dates endpoint")
    return dates


def send_discord(webhook, content):
    parts = urlsplit(webhook)
    query = dict(parse_qsl(parts.query))
    query["wait"] = "true"
    url = urlunsplit(parts._replace(query=urlencode(query)))
    payload = json.dumps({"content": content, "allowed_mentions": {"parse": []}}).encode("utf-8")
    request = Request(url, data=payload, headers={
        "Content-Type": "application/json", "User-Agent": "ExamMonitor/1.0"
    }, method="POST")
    with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        response.read()


class DiscordLogHandler(logging.Handler):
    """Batch logs per check; report delivery failures locally without recursion."""

    def __init__(self, webhook):
        super().__init__(level=logging.INFO)
        self.webhook = webhook
        self.lines = []
        self.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))

    def emit(self, record):
        self.lines.append(self.format(record)[:1900])

    def flush(self):
        lines, self.lines = self.lines, []
        if not lines:
            return
        chunks = [""]
        for line in lines:
            if len(chunks[-1]) + len(line) + 1 > 1900:
                chunks.append("")
            chunks[-1] += line + "\n"
        try:
            for chunk in chunks:
                if chunk:
                    send_discord(self.webhook, chunk.rstrip())
        except (OSError, URLError, ValueError) as error:
            detail = f"HTTP {error.code}" if isinstance(error, HTTPError) else type(error).__name__
            print(f"Discord log delivery failed ({detail}); logs remain in local output.", file=sys.stderr)


def availability_message(center, url, dates):
    # Bound the preview so even large responses fit Discord's message limit.
    preview = json.dumps(dates, ensure_ascii=True).replace("`", "\\u0060")
    if len(preview) > 1400:
        preview = preview[:1400] + " ... (preview truncated)"
    return (f"Exam dates available! Center {center}, category 1: {len(dates)} result(s).\n"
            f"Book: https://exam-booking.sa.gov.ge/\n"
            f"Source: {url}\n```json\n{preview}\n```")


def log_failure(context, error):
    # Never log exception URLs: Discord URLs contain a secret token.
    detail = f"HTTP {error.code}" if isinstance(error, HTTPError) else type(error).__name__
    LOG.error("%s failed (%s); will try again next cycle", context, detail)


def check_once(webhook):
    success = True
    for center, url in ENDPOINTS.items():
        try:
            dates = fetch_dates(url)
            LOG.info("Center %s: %s available result(s)", center, len(dates))
            if dates:
                send_discord(webhook, availability_message(center, url, dates))
                LOG.info("Center %s: Discord notification sent", center)
        except (OSError, URLError, ValueError) as error:
            log_failure(f"Center {center} check or notification", error)
            success = False
    return success


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--once", action="store_true", help="Check both endpoints once, then exit")
    modes.add_argument("--test-notification", action="store_true", help="Send one test message, then exit")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        webhook = load_webhook()
        log_webhook = load_webhook("DISCORD_LOG_WEBHOOK_URL", required=False)
    except ValueError as error:
        LOG.error("%s", error)
        return 1
    except OSError:
        LOG.error("Could not read .env")
        return 1
    handler = DiscordLogHandler(log_webhook) if log_webhook else None
    if handler:
        LOG.addHandler(handler)
    try:
        return run(webhook, args, handler)
    finally:
        if handler:
            handler.flush()
            LOG.removeHandler(handler)
            handler.close()


def run(webhook, args, log_handler=None):
    if args.test_notification:
        try:
            send_discord(webhook, "Exam Monitor test: Discord notifications are working.")
            LOG.info("Test notification sent")
            return 0
        except (OSError, URLError, ValueError) as error:
            log_failure("Test notification", error)
            return 1
    if args.once:
        return 0 if check_once(webhook) else 1
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    LOG.info("Monitoring centers 15 and 7 every 10 minutes; first check now")
    while not stop.is_set():
        started = time.monotonic()
        check_once(webhook)
        if log_handler:
            log_handler.flush()
        stop.wait(max(0, INTERVAL_SECONDS - (time.monotonic() - started)))
    LOG.info("Monitor stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
