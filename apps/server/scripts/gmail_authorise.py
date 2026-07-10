#!/usr/bin/env python3
"""One-time interactive Gmail OAuth consent — docs/API.md §3b.

Run once, in a terminal, on the household Mac:

    .venv/bin/python scripts/gmail_authorise.py

It opens a browser, the user grants **read-only** access (the single
``gmail.readonly`` scope, nothing else), and a refresh token lands at
``KAKEIBO_GMAIL_TOKEN_PATH`` (``data/secrets/gmail-token.json``, gitignored).
The read-only sync (``scripts/pull_rental_emails.py``) then runs unattended.

**Read-only, always.** This script requests exactly one scope,
``https://www.googleapis.com/auth/gmail.readonly`` — no send, modify, or
labels grant is ever requested here or anywhere in Kakeibo (docs/API.md §3a,
ARCHITECTURE.md §5.2).

⚠️→ note (resolved for docs/API.md §3b): Google expires refresh tokens every 7
days for OAuth apps left in **Testing** publishing status. To avoid weekly
re-authorising, set the Cloud consent screen to **"In production"** (option
(a) in §3b): because ``gmail.readonly`` is a restricted scope, Google shows one
"unverified app" interstitial at grant time (click *Advanced → go to
kakeibo-local*), after which the token is long-lived. If you prefer to stay in
Testing (option (b)), ``/api/health`` will report ``gmail: not_configured``
when the token expires and you re-run this script. Prefer (a).
"""
from __future__ import annotations

import sys
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from app.config import get_settings  # noqa: E402
from app.integrations.gmail import GMAIL_READONLY_SCOPE  # noqa: E402


def main() -> int:
    settings = get_settings()
    creds_path = Path(settings.gmail_credentials_path)
    token_path = Path(settings.gmail_token_path)

    if not creds_path.exists():
        print(
            f"Missing OAuth client secret at {creds_path}.\n"
            "Create it: Google Cloud console → project kakeibo-local → enable Gmail API →\n"
            "OAuth consent (External, add yourself as a test user) → Credentials →\n"
            "OAuth client ID → Desktop app → download JSON → save to that path (docs/API.md §3b)."
        )
        return 1

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow  # lazy — only this script needs it
    except ImportError:
        print("google-auth-oauthlib is not installed. Run: .venv/bin/pip install -r requirements.txt")
        return 1

    # A single-scope, read-only consent. run_local_server opens the browser and
    # captures the redirect on a loopback port (the Desktop-app flow).
    flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), [GMAIL_READONLY_SCOPE])
    creds = flow.run_local_server(port=0)

    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json())
    print(f"Read-only Gmail token written to {token_path}. You can now run scripts/pull_rental_emails.py.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
