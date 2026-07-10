"""Gmail read-only client — app/integrations/gmail.py, docs/API.md §3.

No live Google: a fake service is injected (docs/phases/PHASE-5 item 5 "Mock
the Gmail service in tests"). Also the read-only-boundary proof: the module
exposes exactly three read methods and names no send/modify/labels call
(docs/phases/PHASE-5 acceptance).
"""
from __future__ import annotations

import base64
from pathlib import Path

import pytest

from app.integrations.gmail import GmailClient, NotConfigured


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode()


class _Exec:
    def __init__(self, result: dict) -> None:
        self._result = result

    def execute(self) -> dict:
        return self._result


class _Attachments:
    def __init__(self, svc: "FakeGmailService") -> None:
        self.svc = svc

    def get(self, userId: str, messageId: str, id: str) -> _Exec:  # noqa: A002 - Gmail's param name
        return _Exec({"data": self.svc.attachments[id]})


class _Messages:
    def __init__(self, svc: "FakeGmailService") -> None:
        self.svc = svc

    def list(self, userId: str, q: str, pageToken: str | None = None) -> _Exec:
        self.svc.last_query = q
        page = self.svc.pages.get(pageToken, self.svc.pages[None])
        return _Exec(page)

    def get(self, userId: str, id: str, format: str) -> _Exec:  # noqa: A002
        return _Exec(self.svc.by_id[id])

    def attachments(self) -> _Attachments:
        return _Attachments(self.svc)


class _Users:
    def __init__(self, svc: "FakeGmailService") -> None:
        self.svc = svc

    def messages(self) -> _Messages:
        return _Messages(self.svc)


class FakeGmailService:
    """Minimal stand-in for a googleapiclient Gmail resource."""

    def __init__(self, pages: dict, by_id: dict | None = None, attachments: dict | None = None) -> None:
        self.pages = pages
        self.by_id = by_id or {}
        self.attachments = attachments or {}
        self.last_query: str | None = None

    def users(self) -> _Users:
        return _Users(self)


def test_not_configured_when_no_token_file(tmp_path: Path):
    with pytest.raises(NotConfigured):
        GmailClient(credentials_path=str(tmp_path / "c.json"), token_path=str(tmp_path / "missing-token.json"))


def test_search_returns_refs_and_follows_pagination():
    service = FakeGmailService(
        pages={
            None: {"messages": [{"id": "a", "threadId": "t1"}], "nextPageToken": "p2"},
            "p2": {"messages": [{"id": "b", "threadId": "t2"}]},
        }
    )
    client = GmailClient(service=service)
    refs = client.search("subject:rent")
    assert [r.message_id for r in refs] == ["a", "b"]
    assert service.last_query == "subject:rent"


def test_fetch_message_and_attachment():
    service = FakeGmailService(
        pages={None: {"messages": []}},
        by_id={"m1": {"id": "m1", "payload": {"headers": []}}},
        attachments={"att1": _b64(b"%PDF-1.4 fake pdf bytes")},
    )
    client = GmailClient(service=service)
    assert client.fetch_message("m1")["id"] == "m1"
    assert client.fetch_attachment("m1", "att1") == b"%PDF-1.4 fake pdf bytes"


def test_client_exposes_exactly_three_read_methods():
    public = {name for name in vars(GmailClient) if not name.startswith("_")}
    assert public == {"search", "fetch_message", "fetch_attachment"}


def test_no_write_scopes_or_verbs_in_gmail_module():
    """docs/phases/PHASE-5 acceptance: no modify/send/labels/trash. Enforced in
    CI, not just by scope."""
    import app.integrations.gmail as mod

    source = Path(mod.__file__).read_text().lower()
    for forbidden in (".send(", ".modify(", ".trash(", ".insert(", ".delete(", ".labels(", "gmail.send", "gmail.modify"):
        assert forbidden not in source, f"found a write reference {forbidden!r} in gmail.py"
    # The only scope named anywhere is gmail.readonly.
    assert "gmail.modify" not in source and "gmail.labels" not in source
    assert "readonly" in source
