from __future__ import annotations

import base64
import logging
import os
import re
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


class GmailClient:
    def __init__(self, credentials_dir: str = "./credentials"):
        self.credentials_dir = Path(credentials_dir)
        self.service = None

    def authenticate(self):
        token_path = self.credentials_dir / "token.json"
        creds_path = self.credentials_dir / "credentials.json"
        creds = None

        if token_path.exists():
            creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                    logger.info("Token refreshed successfully.")
                except Exception as e:
                    logger.error("Token refresh failed — re-auth required: %s", e)
                    creds = None

            if not creds:
                if not creds_path.exists():
                    raise FileNotFoundError(
                        f"credentials.json not found at {creds_path}. "
                        "Download it from Google Cloud Console."
                    )
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(creds_path), SCOPES
                )
                creds = flow.run_local_server(port=0)

            with open(token_path, "w") as f:
                f.write(creds.to_json())
            logger.info("Token saved to %s", token_path)

        self.service = build("gmail", "v1", credentials=creds)
        logger.info("Gmail API authenticated.")

    def fetch_new_messages(self, since_timestamp: int) -> list[dict]:
        if not self.service:
            self.authenticate()

        query = f"after:{since_timestamp}"
        msg_refs = []
        page_token = None

        # Paginate through all results
        while True:
            try:
                kwargs = {"userId": "me", "q": query, "maxResults": 500}
                if page_token:
                    kwargs["pageToken"] = page_token
                response = self.service.users().messages().list(**kwargs).execute()
            except HttpError as e:
                logger.error("Failed to list messages: %s", e)
                break

            msg_refs.extend(response.get("messages", []))
            page_token = response.get("nextPageToken")
            if not page_token:
                break

        logger.info("Found %d new message(s) since %d", len(msg_refs), since_timestamp)

        messages_out = []
        for ref in msg_refs:
            try:
                msg = (
                    self.service.users()
                    .messages()
                    .get(userId="me", id=ref["id"], format="full")
                    .execute()
                )
                messages_out.append(self._parse_message(msg))
            except HttpError as e:
                logger.error("Failed to fetch message %s: %s", ref["id"], e)

        return messages_out

    def fetch_thread_messages(self, thread_id: str) -> list[dict]:
        """Return all messages in a thread, oldest first."""
        if not self.service:
            self.authenticate()

        try:
            thread = (
                self.service.users()
                .threads()
                .get(userId="me", id=thread_id, format="full")
                .execute()
            )
        except HttpError as e:
            logger.error("Failed to fetch thread %s: %s", thread_id, e)
            return []

        messages = thread.get("messages", [])
        parsed = [self._parse_message(m) for m in messages]
        logger.info("Fetched %d message(s) from thread %s", len(parsed), thread_id)
        return parsed

    def _parse_message(self, msg: dict) -> dict:
        headers = {
            h["name"].lower(): h["value"]
            for h in msg.get("payload", {}).get("headers", [])
        }
        return {
            "id": msg["id"],
            "thread_id": msg["threadId"],
            "sender": headers.get("from", ""),
            "subject": headers.get("subject", "(no subject)"),
            "date": headers.get("date", ""),
            "body_text": self.decode_body(msg.get("payload", {})),
            "snippet": msg.get("snippet", ""),
        }

    def decode_body(self, payload: dict) -> str:
        mime_type = payload.get("mimeType", "")

        if mime_type == "text/plain":
            data = payload.get("body", {}).get("data", "")
            if data:
                return self._strip_quotes(self._b64decode(data))

        if mime_type == "text/html":
            # Will be used as fallback below; skip for now
            pass

        parts = payload.get("parts", [])
        plain_text = ""
        html_text = ""

        for part in parts:
            result = self.decode_body(part)
            if part.get("mimeType") == "text/plain" and not plain_text:
                plain_text = result
            elif part.get("mimeType") == "text/html" and not html_text:
                html_text = result
            elif result and not plain_text:
                plain_text = result

        return plain_text or html_text

    @staticmethod
    def _b64decode(data: str) -> str:
        try:
            padded = data + "=" * (4 - len(data) % 4)
            return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")
        except Exception:
            return ""

    @staticmethod
    def _strip_quotes(text: str) -> str:
        lines = text.splitlines()
        cleaned = [line for line in lines if not line.startswith(">")]
        return "\n".join(cleaned).strip()


if __name__ == "__main__":
    import time

    logging.basicConfig(level=logging.INFO)
    credentials_dir = os.getenv("CREDENTIALS_DIR", "./credentials")
    client = GmailClient(credentials_dir=credentials_dir)
    client.authenticate()

    since = int(time.time()) - 7 * 24 * 3600  # last 7 days
    messages = client.fetch_new_messages(since)
    print(f"\nFetched {len(messages)} message(s):")
    for m in messages[:5]:
        print(f"  [{m['date']}] {m['sender']} — {m['subject']}")
