"""Gmail read-only client — docs/API.md §3.

Exposes exactly **three read methods**: ``search / fetch_message /
fetch_attachment``. The OAuth scope is the single ``gmail.readonly`` (§3a) and
the read-only boundary is enforced twice over:

1. **By scope** — the token minted by ``scripts/gmail_authorise.py`` carries
   only ``https://www.googleapis.com/auth/gmail.readonly``. No send, no modify,
   no labels grant exists.
2. **By code shape** — this module only ever reaches
   ``users().messages().list`` / ``.get`` and ``...attachments().get``. It
   never imports, names, or scaffolds a send/modify/labels/trash call, even in
   a comment with a real method path (same review-blocker discipline as
   ``integrations/starling.py`` / ``trading212.py``, docs/ARCHITECTURE.md §5.2;
   docs/phases/PHASE-5-tax.md acceptance: "no modify/send/labels imports"). The
   ``tests/test_gmail_client.py`` grep enforces it in CI.

No real Google credentials exist yet (docs/SECRETS.md) — the whole pipeline is
built and tested against a **fake service object** injected into the
constructor; the ``google-*`` libraries are imported lazily, only when a real
token has to be loaded, so importing this module (and running the test suite)
never requires them to be installed. Absent a token file the client raises
:class:`NotConfigured`, which the caller degrades into a ``not_configured``
sync row rather than crashing (docs/PLAN.md §6 rule 7).
"""
from __future__ import annotations

import base64
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

# The one and only OAuth scope this app ever requests (docs/API.md §3a).
GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"


class GmailError(Exception):
    """Base class for Gmail client failures."""


class NotConfigured(GmailError):
    """No OAuth token file exists yet (docs/SECRETS.md). The caller records a
    `not_configured` outcome rather than crashing (docs/PLAN.md §6 rule 7)."""


class GmailUnavailable(GmailError):
    """A Google API call failed (network, auth expiry, quota)."""


class GmailService(Protocol):
    """The narrow slice of the ``googleapiclient`` resource this client uses —
    just enough to type the injected fake in tests. Real usage is
    ``service.users().messages().list(...).execute()`` etc."""

    def users(self) -> Any: ...


@dataclass
class GmailMessageRef:
    message_id: str
    thread_id: str | None = None


@dataclass
class GmailAttachment:
    attachment_id: str
    filename: str
    mime_type: str
    data: bytes = field(repr=False)


def _load_service(credentials_path: str, token_path: str) -> GmailService:
    """Build a real read-only Gmail service from a stored token. Imported
    lazily so this module (and the test suite, which injects a fake service)
    never needs ``google-*`` installed. Read-only: refreshes an existing token
    but never initiates consent — that is ``scripts/gmail_authorise.py``'s job
    (docs/API.md §3b)."""
    if not Path(token_path).exists():
        raise NotConfigured(f"No Gmail token at {token_path} — run scripts/gmail_authorise.py once")
    try:  # lazy import — see module docstring
        from google.auth.transport.requests import Request  # type: ignore
        from google.oauth2.credentials import Credentials  # type: ignore
        from googleapiclient.discovery import build  # type: ignore
    except ImportError as exc:  # pragma: no cover - only when deps genuinely absent
        raise GmailUnavailable(
            "google-api-python-client / google-auth are not installed — "
            "pip install -r requirements.txt"
        ) from exc

    creds = Credentials.from_authorized_user_file(token_path, [GMAIL_READONLY_SCOPE])
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        Path(token_path).write_text(creds.to_json())
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


class GmailClient:
    """Read-only Gmail client. Construct with ``service=`` (a fake) in tests;
    in production omit it and a real service is lazily built from the stored
    token."""

    def __init__(
        self,
        credentials_path: str = "",
        token_path: str = "",
        *,
        service: GmailService | None = None,
        user_id: str = "me",
    ) -> None:
        self._user_id = user_id
        if service is not None:
            self._service: GmailService = service
        else:
            self._service = _load_service(credentials_path, token_path)

    def search(self, query: str, *, max_results: int = 200) -> list[GmailMessageRef]:
        """``users.messages.list`` with the configured query (docs/API.md §3c),
        following ``nextPageToken`` up to ``max_results``. Returns message refs
        only — bodies/attachments are fetched per-id by the caller."""
        refs: list[GmailMessageRef] = []
        page_token: str | None = None
        try:
            while len(refs) < max_results:
                resp = (
                    self._service.users()
                    .messages()
                    .list(userId=self._user_id, q=query, pageToken=page_token)
                    .execute()
                )
                for m in resp.get("messages", []):
                    refs.append(GmailMessageRef(message_id=m["id"], thread_id=m.get("threadId")))
                page_token = resp.get("nextPageToken")
                if not page_token:
                    break
        except NotConfigured:
            raise
        except Exception as exc:  # googleapiclient raises HttpError et al.
            raise GmailUnavailable(f"Gmail search failed: {exc}") from exc
        return refs[:max_results]

    def fetch_message(self, message_id: str) -> dict[str, Any]:
        """``users.messages.get`` (``format='full'``) — the full message
        payload (headers, body, attachment metadata) for one id."""
        try:
            return (
                self._service.users()
                .messages()
                .get(userId=self._user_id, id=message_id, format="full")
                .execute()
            )
        except Exception as exc:
            raise GmailUnavailable(f"Gmail fetch_message({message_id}) failed: {exc}") from exc

    def fetch_attachment(self, message_id: str, attachment_id: str) -> bytes:
        """``users.messages.attachments.get`` — the decoded bytes of one
        attachment (Gmail returns URL-safe base64)."""
        try:
            resp = (
                self._service.users()
                .messages()
                .attachments()
                .get(userId=self._user_id, messageId=message_id, id=attachment_id)
                .execute()
            )
        except Exception as exc:
            raise GmailUnavailable(f"Gmail fetch_attachment({message_id}/{attachment_id}) failed: {exc}") from exc
        return base64.urlsafe_b64decode(resp["data"])
