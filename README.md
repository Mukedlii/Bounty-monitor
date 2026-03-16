# Bounty Monitor (Algora + IssueHunt → Telegram)

GitHub Actions workflow that checks for new bounties and sends a Telegram message **only for items not seen before**.

## Setup

1. Create a Telegram bot via @BotFather
2. Get your chat id (e.g. from @userinfobot or by sending a message and checking updates)
3. In your GitHub repo settings → **Settings → Secrets and variables → Actions**, add secrets:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`

## Run

- Automatic: runs 3× per day (cron in UTC)
- Manual: Actions → **Bounty Monitor** → **Run workflow**

## Notes about dedupe

The script stores IDs in `seen_bounties.json`. The workflow persists it via GitHub Actions cache, so repeated runs do not resend the same bounty.
