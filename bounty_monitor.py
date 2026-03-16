"""Bounty Monitor (Algora.io + IssueHunt)

- Runs via GitHub Actions on a schedule.
- Sends Telegram notifications only for NEW bounties (deduped via a persisted state file).

Required GitHub Secrets:
  - TELEGRAM_BOT_TOKEN
  - TELEGRAM_CHAT_ID
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from typing import Any

import requests

ALGORA_API = "https://console.algora.io/api/bounties?limit=50&status=active"
ISSUEHUNT_API = "https://issuehunt.io/api/v1/issues?state=open&per_page=50&sort=created"

STATE_FILE = "seen_bounties.json"

MIN_AMOUNT_USD = int(os.environ.get("MIN_AMOUNT_USD", "50"))

PREFERRED_LANGS = ["JavaScript", "TypeScript", "Python", "CSS", "HTML"]

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")


def load_seen() -> set[str]:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return set(map(str, data))
        except Exception:
            return set()
    return set()


def save_seen(seen: set[str]) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(seen), f, ensure_ascii=False, indent=2)


def _requests_get_json(url: str) -> Any:
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    return r.json()


def fetch_algora() -> list[dict]:
    try:
        data = _requests_get_json(ALGORA_API)
        items = data.get("items", []) if isinstance(data, dict) else []
        print(f"[Algora] fetched: {len(items)}")
        return items
    except Exception as e:
        print(f"[Algora] fetch error: {e}")
        return []


def parse_algora(items: list[dict]) -> list[dict]:
    out: list[dict] = []
    for item in items:
        amount_cents = int(item.get("amount") or 0)
        amount_usd = amount_cents // 100
        if amount_usd < MIN_AMOUNT_USD:
            continue

        issue = item.get("issue") or {}
        repo_owner = item.get("repo_owner") or ""
        repo_name = item.get("repo_name") or ""

        title = (issue.get("title") or "No title").strip()
        url = (issue.get("html_url") or "").strip() or f"https://github.com/{repo_owner}/{repo_name}"

        bounty_id = str(item.get("id") or url)

        out.append(
            {
                "id": f"algora_{bounty_id}",
                "platform": "Algora",
                "title": title,
                "repo": f"{repo_owner}/{repo_name}".strip("/"),
                "url": url,
                "amount_usd": amount_usd,
                "language": (item.get("language") or ""),
                "created_at": item.get("created_at") or "",
            }
        )
    return out


def fetch_issuehunt() -> list[dict]:
    try:
        data = _requests_get_json(ISSUEHUNT_API)
        items = data.get("data", data) if isinstance(data, dict) else data
        if not isinstance(items, list):
            items = []
        print(f"[IssueHunt] fetched: {len(items)}")
        return items
    except Exception as e:
        print(f"[IssueHunt] fetch error: {e}")
        return []


def parse_issuehunt(items: list[dict]) -> list[dict]:
    out: list[dict] = []
    for item in items:
        amt = item.get("fund_amount", item.get("amount", 0))
        try:
            amount_usd = int(float(str(amt).replace("$", "").replace(",", "").strip() or 0))
        except Exception:
            amount_usd = 0

        if amount_usd < MIN_AMOUNT_USD:
            continue

        issue_id = str(item.get("id") or item.get("uid") or item.get("issue", {}).get("id") or item.get("url") or "")
        title = (item.get("title") or item.get("issue", {}).get("title") or "No title").strip()
        url = (item.get("url") or item.get("html_url") or "https://issuehunt.io").strip()
        language = (item.get("language") or "")
        repo = item.get("full_name") or item.get("repo", {}).get("full_name") or "unknown"

        out.append(
            {
                "id": f"issuehunt_{issue_id}",
                "platform": "IssueHunt",
                "title": title,
                "repo": repo,
                "url": url,
                "amount_usd": amount_usd,
                "language": language,
                "created_at": item.get("created_at") or "",
            }
        )
    return out


def is_preferred(b: dict) -> bool:
    lang = (b.get("language") or "").strip()
    if not lang:
        return True
    return any(p.lower() in lang.lower() for p in PREFERRED_LANGS)


def format_message(new_items: list[dict]) -> str:
    if not new_items:
        return ""

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines: list[str] = [f"<b>{len(new_items)} új bounty!</b> ({now})\n"]

    new_items = sorted(new_items, key=lambda x: int(x.get("amount_usd") or 0), reverse=True)

    for b in new_items[:15]:
        lang_tag = f" [{b['language']}]" if b.get("language") else ""
        pref = " ⭐" if is_preferred(b) else ""
        title = (b.get("title") or "").strip().replace("\n", " ")
        if len(title) > 80:
            title = title[:77] + "..."

        lines.append(
            f"<b>${int(b['amount_usd']):,}</b>{pref} — {title}\n"
            f"{b.get('platform')} · {b.get('repo','')}{lang_tag}\n"
            f"{b.get('url','')}\n"
        )

    if len(new_items) > 15:
        lines.append(f"\n...és még {len(new_items) - 15} bounty.")

    return "\n".join(lines).strip()


def send_telegram(text: str) -> None:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("[WARN] TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID missing; printing only")
        print(text)
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    r = requests.post(url, json=payload, timeout=20)
    r.raise_for_status()


def main() -> None:
    print(f"[START] {datetime.now().isoformat()}")

    seen = load_seen()
    print(f"[STATE] seen: {len(seen)}")

    all_items: list[dict] = []
    all_items += parse_algora(fetch_algora())
    # small delay to be polite
    time.sleep(0.4)
    all_items += parse_issuehunt(fetch_issuehunt())

    # de-dupe inside a run
    uniq: dict[str, dict] = {}
    for b in all_items:
        bid = str(b.get("id") or "")
        if bid:
            uniq[bid] = b
    all_items = list(uniq.values())

    new_items = [b for b in all_items if str(b.get("id")) not in seen]
    print(f"[NEW] {len(new_items)}")

    if new_items:
        msg = format_message(new_items)
        if msg:
            send_telegram(msg)
            print("[OK] telegram sent")

        for b in new_items:
            seen.add(str(b.get("id")))
        save_seen(seen)
        print(f"[STATE] saved: {len(seen)}")
    else:
        print("[OK] no new bounties")


if __name__ == "__main__":
    main()
