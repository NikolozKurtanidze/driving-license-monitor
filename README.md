# Exam Monitor

A lightweight Python monitor for Georgian driving theory exam availability, with checks every 10 minutes and Discord alerts and logs.

A Python 3.9+ background worker with no third-party dependencies. Checks category 1 at centers 15 and 7 immediately, then every 600 seconds. No inbound port or public server URL is needed.

Each nonempty JSON array triggers a Discord message containing the center, result count, response preview, and booking link. Empty arrays send no availability alerts. **Alerts repeat every 10 minutes while results remain nonempty**, even if the dates have not changed. Invalid JSON, unexpected response shapes, HTTP errors, and timeouts are logged; the other center is still checked and polling continues. Failed notifications are attempted again on the next check if dates are still available; old results are not queued.

## Set up Discord

1. Create or select a normal text channel in your Discord server (not a forum channel).
2. Open **Server Settings → Integrations → Webhooks → New Webhook**. You need the **Manage Webhooks** permission.
3. Name it **Exam Monitor**, select your channel, save, and click **Copy Webhook URL**.
4. In this folder, copy the configuration template:

   ```sh
   cp .env.example .env
   ```

5. Open `.env` and replace the example URL with the copied URL. Keep this URL private: it allows messages to be posted to your channel. `.env` is excluded from Git. An exported `DISCORD_WEBHOOK_URL` takes precedence over this file.
6. For device alerts, enable notifications for this channel (All Messages) and allow Discord notifications on your device. Messages do not ping everyone or roles.

Discord's [webhook setup guide](https://support.discord.com/hc/en-us/articles/228383668-Intro-to-Webhooks) and [webhook API reference](https://docs.discord.com/developers/resources/webhook).

## Separate log channel

Create another webhook using the same Discord steps, selecting a separate text channel for logs. Paste its URL into `DISCORD_LOG_WEBHOOK_URL` in `.env`:

```dotenv
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/ALERT_ID/ALERT_TOKEN
DISCORD_LOG_WEBHOOK_URL=https://discord.com/api/webhooks/LOG_ID/LOG_TOKEN
```

The log channel receives timestamped startup/shutdown messages, results for both centers (including empty arrays), notification confirmations, and check errors. Logs are batched after each check; local terminal/file logs continue as before. Leaving the second URL blank disables Discord logging. Exported environment settings take precedence over `.env`.

Restart the monitor after changing `.env`. `--test-notification` sends an availability-channel test and records its result in the log channel. Log delivery failures are reported locally, do not stop polling, and are not retried; subsequent batches are attempted normally. A successful test exit confirms the availability webhook only; check the log channel or local output to verify log delivery.

## Run

In a terminal in this folder:

```sh
python3 monitor.py --test-notification
python3 monitor.py
```

The first command sends a test message and exits. The second runs continuously; stop with Ctrl+C. To check both endpoints just once (and notify if available):

```sh
python3 monitor.py --once
```

For a background process on macOS/Linux:

```sh
nohup python3 -u monitor.py > monitor.log 2>&1 &
echo $! > monitor.pid
```

View activity with `tail -f monitor.log`. To stop that process, use `kill "$(cat monitor.pid)"` (the PID file is only for the most recently started background process). Run only one instance to avoid duplicate alerts.

The machine must remain awake and connected to the internet. This background command does not restart after a reboot. For continuous hosting, run `python3 -u monitor.py` as a worker under your server's process manager with an automatic restart policy, setting `DISCORD_WEBHOOK_URL` as an environment secret. On macOS, `caffeinate -i python3 monitor.py` prevents idle sleep while running in the foreground, but does not guarantee operation with the laptop lid closed.

Requests time out after 30 seconds. Logs show HTTP status codes or error types without exposing the webhook URL. A `--once` or test failure exits with status 1. If the booking service starts requiring authentication or changes its response format, the monitor will log failures and need updating.

## Tests

```sh
python3 -m unittest -v
```

Tests use mocked HTTP responses and do not send real Discord messages.

## Disclaimer

This software is provided “as is,” without warranty. Users are responsible for their use of the software and for complying with applicable laws and service terms. The authors do not endorse unlawful or abusive use and disclaim liability to the fullest extent permitted by applicable law.
