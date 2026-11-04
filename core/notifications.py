import os
import logging
from typing import Any, Dict, Optional
import httpx

from core.logger import log

class NotificationService:
    """
    Multi-channel real-time cloud notification service.
    Dispatches alerts to Discord and Telegram when job applications are submitted or boosted.
    Grounded in candidate Avinash Vishnu Talpade.
    """

    def __init__(self):
        self.discord_webhook = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
        self.telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        self.telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()

    @property
    def is_discord_enabled(self) -> bool:
        return bool(self.discord_webhook and self.discord_webhook.startswith("https://discord.com/api/webhooks"))

    @property
    def is_telegram_enabled(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)

    def notify_application_submitted(
        self,
        platform: str,
        job_title: str,
        company: str,
        job_url: str,
        status: str = "APPLIED",
        match_score: float = 0.0,
        notes: str = ""
    ) -> Dict[str, bool]:
        """
        Sends an instant alert to Discord and Telegram when an application is submitted.
        """
        results = {"discord": False, "telegram": False}
        if not (self.is_discord_enabled or self.is_telegram_enabled):
            return results

        score_text = f"{match_score * 100:.1f}%" if match_score > 0 else "N/A"
        clean_url = (job_url or "").split("?")[0]

        # 1. Discord Webhook
        if self.is_discord_enabled:
            try:
                discord_payload = {
                    "username": "Aether CareerOS Bot",
                    "avatar_url": "https://raw.githubusercontent.com/talpadeavi03/auto-apply-slm/main/reports/favicon.ico",
                    "embeds": [
                        {
                            "title": f"🚀 Applied: {job_title} @ {company}",
                            "color": 0x10B981 if "APPLIED" in status else 0xF59E0B,
                            "fields": [
                                {"name": "Candidate", "value": "Avinash Vishnu Talpade (Cloud Engineer)", "inline": True},
                                {"name": "Platform", "value": platform.capitalize(), "inline": True},
                                {"name": "Status", "value": f"`{status}`", "inline": True},
                                {"name": "AI Match Score", "value": score_text, "inline": True},
                                {"name": "Job Link", "value": f"[View Posting]({clean_url})" if clean_url else "N/A", "inline": True},
                            ],
                            "footer": {"text": "Aether CareerOS — 100% Free Autonomous Cloud Engine"}
                        }
                    ]
                }
                with httpx.Client(timeout=8.0) as client:
                    resp = client.post(self.discord_webhook, json=discord_payload)
                    results["discord"] = resp.status_code in (200, 204)
                    if results["discord"]:
                        log.info(f"✓ Dispatched Discord notification for {job_title} at {company}")
            except Exception as e:
                log.debug(f"Discord notification note: {e}")

        # 2. Telegram Bot
        if self.is_telegram_enabled:
            try:
                tg_text = (
                    f"🚀 *Job Application Submitted*\n\n"
                    f"👤 *Candidate:* Avinash Vishnu Talpade\n"
                    f"🏢 *Company:* {company}\n"
                    f"💼 *Role:* {job_title}\n"
                    f"🌐 *Platform:* {platform.capitalize()}\n"
                    f"🎯 *AI Match:* {score_text}\n"
                    f"📊 *Status:* `{status}`\n"
                    f"🔗 [Job Link]({clean_url})\n\n"
                    f"⚡ _Aether CareerOS Cloud Worker_"
                )
                tg_url = f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage"
                tg_payload = {
                    "chat_id": self.telegram_chat_id,
                    "text": tg_text,
                    "parse_mode": "Markdown",
                    "disable_web_page_preview": True
                }
                with httpx.Client(timeout=8.0) as client:
                    resp = client.post(tg_url, json=tg_payload)
                    results["telegram"] = resp.status_code == 200
                    if results["telegram"]:
                        log.info(f"✓ Dispatched Telegram notification for {job_title} at {company}")
            except Exception as e:
                log.debug(f"Telegram notification note: {e}")

        return results

    def notify_summary(self, applied_count: int, inspected_count: int, boosted: list = None) -> None:
        """Sends a high-level summary notification at the end of a scheduled cloud run."""
        if not (self.is_discord_enabled or self.is_telegram_enabled):
            return

        boost_str = ", ".join(boosted) if boosted else "None"
        msg = (
            f"📊 *Aether CareerOS Run Complete*\n\n"
            f"✅ *New Applications:* {applied_count}\n"
            f"🔍 *Jobs Inspected:* {inspected_count}\n"
            f"⚡ *Profiles Boosted ('Active Today'):* {boost_str}\n"
            f"🤖 *Dataset Growth:* Saved & synchronized for SLM fine-tuning."
        )

        if self.is_telegram_enabled:
            try:
                with httpx.Client(timeout=8.0) as client:
                    client.post(
                        f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage",
                        json={"chat_id": self.telegram_chat_id, "text": msg, "parse_mode": "Markdown"}
                    )
            except Exception:
                pass

        if self.is_discord_enabled:
            try:
                with httpx.Client(timeout=8.0) as client:
                    client.post(
                        self.discord_webhook,
                        json={
                            "username": "Aether CareerOS Bot",
                            "embeds": [{
                                "title": "🏁 Cloud Automation Cycle Summary",
                                "color": 0x3B82F6,
                                "description": (
                                    f"**Applications Submitted:** {applied_count}\n"
                                    f"**Jobs Evaluated:** {inspected_count}\n"
                                    f"**Boosted Profiles:** {boost_str}\n"
                                    f"**Cloud Status:** 100% Free Compute, Continuous Training Active"
                                )
                            }]
                        }
                    )
            except Exception:
                pass

notifier = NotificationService()
