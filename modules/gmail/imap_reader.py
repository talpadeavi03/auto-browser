import email
from email.header import decode_header
import imaplib
import os
from typing import Any, Dict, List, Optional
from core.logger import log

class GmailIMAPReader:
    """
    Direct, secure SSL IMAP reader for Gmail using Google App Passwords.
    Monitors candidate inbox for incoming job alerts and recruiter outreach.
    """

    def __init__(
        self,
        username: Optional[str] = None,
        app_password: Optional[str] = None,
        imap_server: str = "imap.gmail.com",
        imap_port: int = 993
    ):
        self.username = username or os.getenv("GMAIL_USER") or os.getenv("GMAIL_ADDRESS") or "talpadeavi0303@gmail.com"
        self.password = (app_password or os.getenv("GMAIL_APP_PASSWORD") or "").replace(" ", "")
        self.imap_server = imap_server
        self.imap_port = imap_port
        self.client: Optional[imaplib.IMAP4_SSL] = None

    def connect(self) -> bool:
        """Connects and authenticates with Gmail over SSL."""
        if not self.password:
            log.warning("No GMAIL_APP_PASSWORD configured. Skipping Gmail IMAP connection.")
            return False

        try:
            log.info(f"Connecting to Gmail IMAP ({self.imap_server}:{self.imap_port}) as {self.username}...")
            self.client = imaplib.IMAP4_SSL(self.imap_server, self.imap_port)
            self.client.login(self.username, self.password)
            log.info(f"✓ Successfully authenticated with Gmail IMAP as {self.username}!")
            return True
        except imaplib.IMAP4.error as e:
            log.warning(f"Gmail IMAP authentication failed: {e}. Check GMAIL_APP_PASSWORD secret.")
            return False
        except Exception as e:
            log.warning(f"Unexpected error connecting to Gmail IMAP: {e}")
            return False

    def close(self) -> None:
        """Closes the IMAP connection safely."""
        if self.client:
            try:
                self.client.close()
                self.client.logout()
            except Exception:
                pass
            self.client = None

    def _decode_str(self, header_val: Optional[str]) -> str:
        """Decodes MIME encoded header strings into unicode."""
        if not header_val:
            return ""
        decoded_parts = decode_header(header_val)
        result = []
        for text, encoding in decoded_parts:
            if isinstance(text, bytes):
                try:
                    result.append(text.decode(encoding or "utf-8", errors="replace"))
                except Exception:
                    result.append(text.decode("latin1", errors="replace"))
            else:
                result.append(str(text))
        return " ".join(result).strip()

    def list_unread_emails(self, max_results: int = 20) -> List[str]:
        """Searches INBOX for unread messages."""
        if not self.client and not self.connect():
            return []

        try:
            self.client.select("INBOX")
            # Search for unread messages
            status, messages = self.client.search(None, "UNSEEN")
            if status != "OK" or not messages or not messages[0]:
                log.info("No unread messages found in Gmail INBOX.")
                return []

            email_ids = messages[0].split()
            # Most recent first
            email_ids.reverse()
            return [msg_id.decode("utf-8") for msg_id in email_ids[:max_results]]
        except Exception as e:
            log.error(f"Error searching unread emails: {e}")
            return []

    def fetch_email(self, msg_id: str, mark_as_read: bool = True) -> Optional[Dict[str, Any]]:
        """
        Fetches an email by ID, decodes subject, sender, and text/html bodies.
        """
        if not self.client and not self.connect():
            return None

        try:
            status, data = self.client.fetch(msg_id, "(RFC822)")
            if status != "OK" or not data or not data[0]:
                return None

            raw_email = data[0][1]
            msg = email.message_from_bytes(raw_email)

            subject = self._decode_str(msg.get("Subject", "No Subject"))
            sender = self._decode_str(msg.get("From", "Unknown"))
            date_str = msg.get("Date", "")

            body_text = ""
            body_html = ""

            if msg.is_multipart():
                for part in msg.walk():
                    content_type = part.get_content_type()
                    content_disposition = str(part.get("Content-Disposition", ""))

                    if "attachment" in content_disposition:
                        continue

                    try:
                        payload = part.get_payload(decode=True)
                        if not payload:
                            continue
                        charset = part.get_content_charset() or "utf-8"
                        decoded_body = payload.decode(charset, errors="replace")

                        if content_type == "text/plain":
                            body_text += decoded_body + "\n"
                        elif content_type == "text/html":
                            body_html += decoded_body + "\n"
                    except Exception:
                        pass
            else:
                try:
                    payload = msg.get_payload(decode=True)
                    if payload:
                        charset = msg.get_content_charset() or "utf-8"
                        decoded_body = payload.decode(charset, errors="replace")
                        if msg.get_content_type() == "text/html":
                            body_html = decoded_body
                        else:
                            body_text = decoded_body
                except Exception:
                    pass

            if mark_as_read:
                self.client.store(msg_id, "+FLAGS", "\\Seen")

            return {
                "id": msg_id,
                "message_id": msg.get("Message-ID", msg_id),
                "subject": subject,
                "sender": sender,
                "date": date_str,
                "body_text": body_text.strip(),
                "body_html": body_html.strip(),
            }
        except Exception as e:
            log.error(f"Error fetching email {msg_id}: {e}")
            return None
