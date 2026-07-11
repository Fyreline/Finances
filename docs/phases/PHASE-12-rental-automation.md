# Phase 12 — rental-statement automation + safe-to-spend/spending period toggle

Owner: Opus (judgment-heavy financial-logic + real-document parsing, same tier as
Phase 4/5/11). Real user feedback, 2026-07-11 (verbatim in HANDOFF's message log, five
items — this phase covers items 1, 2, 5; items 3/4 — desktop panel stability + the
hourglass connector shape — were already fixed and live-verified by the orchestrator
directly, see HANDOFF's Phase-12-adjacent note, nothing further needed there).

## What's already true — read this before writing any code

- **103 real "Monthly Rental Statement" PDFs already sit locally** under
  `tax-documents/2025-26/` and `tax-documents/2026-27/`, pulled by the existing
  `gmail_pull.py` pipeline (see "Gmail pipeline — fixed and live" HANDOFF entry).
  **Zero `RentalLedgerEntry` rows exist** — the tax estimate reads `gross_rents_minor:
  0` and `£0 tax` not because the estimator is broken (it isn't — verified directly,
  it computes correctly once given real numbers) but because nothing has ever turned
  a pulled document into a ledger row. `RentalLedgerEntry.source` already has a
  `'document'` value in its own comment (`app/models.py`) and `tax_document_id` FK —
  the schema anticipated this, it was just never wired up. **This is the root cause of
  the £0 complaint — fix by producing real ledger rows from the real documents, not by
  touching the estimator.**
- **The review queue really is polluted with false positives, confirmed directly**:
  the orchestrator inspected the real pulled-document folders and found `doc_type=
  'rent_statement'` wrongly assigned to at least one actual HSBC *personal current
  account* statement email (subject containing "statement", tripping
  `classify_doc_type`'s generic keyword match) — genuine noise, not a hypothetical.
  The real letting-agent statements have a distinctive, reliable signature, confirmed
  directly against a real message: **sender `...@<letting-agent-domain>`** (real domain
  in PRIVATE.md — the domain, not a display name) **and subject starting with the literal string
  `"Monthly Rental Statement "`** (e.g. `"Monthly Rental Statement for <ref> - <address>
  (<Month Year>)"`). Real folder layout, also confirmed directly: the actual statement
  PDF sits alongside several inline decorative images (`image001.jpg` etc, from the
  email's own logo/signature) — attachment selection must filter to `.pdf` and, if a
  folder has multiple PDFs, prefer the one whose filename contains "Statement".
- **Do not read the real PDFs' financial figures into this conversation, a commit, a
  test fixture, or a doc.** They're real local user data (rent amount, agent
  commission, tenant/property details) — same redaction discipline as everything else
  in this repo, PRIVATE.md's scheme, CLAUDE.md's hard rules. Reading a real file's
  *structure* (field labels, layout, section headings) to write a parser against it is
  fine and necessary; quoting its *numbers* anywhere that gets committed is not. Any
  test fixture PDF must be synthetic (hand-built or generated), with placeholder
  numbers, a placeholder tenant/address, and a placeholder statement reference.

## Item 1 — filter the pull, parse the PDFs, stop the £0 estimate

### 1a. Tighten what counts as an automatable rent statement

`gmail_pull.py`'s existing broad query (`SUBJECT_KEYWORDS` OR'd across many senders)
stays as-is for **discovery** — it's still useful for finding mortgage-interest
certificates, insurance, and HMRC/SA correspondence, which matter for HANDOFF Q1/Q2/Q4
and shouldn't be narrowed away. What needs to change is **classification and
downstream automation**, not the search itself:

- Add a function (e.g. `is_confirmed_rent_statement(from_addr, subject) -> bool`) that
  returns true only for the sender-domain-or-subject-prefix rule above (`@<letting-agent-domain>` in the from address, OR subject starting with `"Monthly Rental
  Statement "`) — not a fuzzy keyword match. This is the gate for both re-classifying
  the review queue and triggering the new PDF-parse-and-ledger pipeline. Don't
  hardcode the agent's domain as a magic string sprinkled through the codebase
  — read it from `tax_config.letting_agent`'s domain if that's derivable, or add one
  clearly-documented constant/config value; use judgement on which is cleaner given
  what's already in `tax_config`.
- Existing `TaxDocument` rows already in the dev/prod DB that are `doc_type=
  'rent_statement'` but fail this confirmed check (like the HSBC one found above) are
  real misclassifications, not borderline cases — reclassify them (`doc_type='other'`
  is the honest label, matching what `classify_doc_type` would emit for something with
  no dedicated type) rather than deleting the row or file; a human can still see them
  under "other" if they want to, they just stop cluttering the rent-statement review
  flow and stop being candidates for auto-ledger extraction. **Do not delete or
  reclassify mortgage-interest-cert/insurance/other rows just because they don't match
  this rent-statement rule** — that's a different, still-valid document category this
  phase isn't touching.
- This reclassification needs to run once against the real local dev/prod DB (same
  category of one-off data-fix as Phase 10's `tax_config` field-setting) — script it,
  don't hand-edit, and report exactly what changed (counts, not the actual subjects/
  amounts) so it's auditable without becoming another redaction leak.

### 1b. PDF text extraction — add a library, no library currently installed

Confirmed via direct check: no PDF-parsing package (`pypdf`, `pdfplumber`, `fitz`/
PyMuPDF) is installed or in `requirements.txt`. Add one — `pdfplumber` is a reasonable
default (good table/layout extraction, pure-Python-friendly, MIT-licensed), but decide
based on what actually works once you're reading the real statement's layout; document
the choice briefly in the completion note. Lazy-import it the same way `gmail.py`
lazy-imports the Google client, so the test suite doesn't require it to be installed
for unrelated tests, and degrade gracefully (parse fails → falls back to the existing
single-amount conservative regex + `reviewed=0`, never a crash) if it's missing at
runtime.

### 1c. Extract the real line items

Write a parser (e.g. `engines/rent_statement_parser.py`, kept pure — takes extracted
text/table data in, returns structured amounts out, no I/O of its own so it's unit-
testable against synthetic fixture text) that pulls, at minimum:

- **Gross rent income** for the statement period.
- **Agent commission/fee** (maps to the existing `agent_fees` allowable-expense type,
  `routers/tax.py`'s `_EXPENSE_TYPES`).
- **Maintenance/upkeep/repair deductions**, if present on that statement (maps to the
  existing `repairs` expense type) — not every statement will have one, that's a valid
  zero, not a parse failure.
- The **statement period** (a month, or a date range) so the extracted amounts land on
  the right `local_date`/`tax_year` in the ledger — don't default to the email's
  received date if the statement itself states a different covered period, they can
  legitimately differ by a few days around month-end.

Read a handful of the real local PDFs first (structure only, per the rule above) to
learn the letting agent's actual layout — likely a simple line-item table ("Rent received",
"Management fee", "Maintenance", "Net remitted" or similar), but confirm rather than
assume. **Be honest about parse confidence**: if the expected line items can't be
found with reasonable certainty (layout doesn't match what was learned, OCR/table
extraction is ambiguous, more than one plausible reading), the whole point of "it
doesn't have to be perfect, just an estimate" is best-effort automation that degrades
to a flagged, human-reviewable state rather than silently inventing or guessing a
split — same spirit as `TAX.md §0`'s never-guess rule, just applied to itemised
document parsing instead of missing config. A partial parse (e.g. rent found, fee
line not found) should populate what it found and leave the rest for a human, not
discard everything.

### 1d. Auto-create ledger entries — this is item 1 AND item 2

Wire the parser's output into new `RentalLedgerEntry` rows automatically, both when a
document is freshly pulled (extend `pull_rental_emails` or the code that calls it) and
retroactively for the 103 already-pulled real statements (a one-off backfill script,
same category as 1a's reclassification — run it, report counts, don't hand-enter).
Concretely, for each confidently-parsed confirmed rent statement:

- Mark the document `reviewed=1` automatically (this *is* the human-review invariant
  being deliberately relaxed for this one narrow, high-confidence, user-requested
  case — see "Hard constraints" below for exactly how far that relaxation should and
  shouldn't go).
- Create one `income` ledger row for the rent, `source='document'`, `tax_document_id`
  set, `expense_type=None`.
- Create one `expense` row per deduction found (`agent_fees`, `repairs`, etc.), same
  `source`/`tax_document_id` linkage.
- **Idempotent**: re-running the backfill or a future pull must not create duplicate
  ledger rows for a document that's already been auto-ledgered — key off
  `tax_document_id` (a document should map to a bounded, predictable set of ledger
  rows; check for existing rows linked to that document before inserting more).
- A document that fails to parse confidently keeps today's behaviour exactly:
  `reviewed=0`, single conservative `amount_minor` (or none), sits in the review
  queue for a human — same as now, no regression.

Once these land for the 103 real statements, `year_summary_payload`'s
`gross_rents_minor` stops being 0 and the tax estimate computes a real (if
imperfect-by-design) figure — verify this live against the real local dev/prod data
directly (never mint a session as the real user to view it through the browser; read
the DB/API response directly, same technique every prior phase used) before calling
this item done.

### 1e. Documents/Ledger UI (`DocumentsPanel.tsx`, `TaxDetail.tsx`)

The document review queue should visibly distinguish "auto-processed, already in your
ledger, nothing to do" from "needs your review" — the review action stops being a
no-op toggle (item 2's ask) because for confirmed rent statements there's now
something real for it to have done. For documents where the auto-parse degrades
(fails or is only partial), the review UI is exactly today's manual entry, still fully
functional — this phase adds automation on top, it doesn't remove the manual path.

## Item 5 — remaining safe-to-spend automation + a calendar/payday toggle

### 5a. Audit what's still manual

Phase 11 already auto-detects `payday_day`/`net_monthly_income_minor` from real
transaction history (manual always wins if set). Once item 1 lands, `tax_setaside_mode
='auto'` (already the default) will finally compute a real, non-zero figure instead of
effectively no-oping against a null estimate. That leaves `flat_share_minor` and
`buffer_minor` in `FinancialConfigLike` as the remaining named-manual fields — audit
each on its own merits rather than assuming both need the same treatment:

- `flat_share_minor` exists specifically to represent the fixed monthly payment to a
  partner for shared costs (HANDOFF Q6) and is deliberately deduplicated against
  auto-detected `committed` recurring-outgoing items (`_flat_share_already_committed`,
  `engines/insights.py`) so it's never double-counted if the same transfer is *also*
  picked up as a recurring committed cost. Check directly against the real local data:
  is this transfer already being detected with reasonable confidence by
  `detect_recurring(direction="out")` the same way other committed costs are? If yes,
  `flat_share_minor` may not need to be a required manual field at all any more — it
  could become an optional override (same "manual always wins, else detected" shape
  as Phase 11's payday/income fields) rather than something that has to be typed in
  before the headline number unlocks. If the detector genuinely can't distinguish it
  confidently from other recurring transfers, leave it manual and say so plainly in
  the completion note — don't force an automation that isn't actually reliable.
- `buffer_minor` is a personal safety-margin *preference*, not a fact to be detected
  from data — it already has a sensible non-zero default (confirmed live: the setup
  form pre-fills `150`). Nothing to automate here beyond what already exists; leave it
  manual, it's supposed to be a choice.

Whatever remains genuinely manual after this audit is fine to stay manual — the goal
is removing friction that has an honest detected answer, not eliminating every input
field regardless of whether automation would be trustworthy.

### 5b. Calendar-month vs payday-to-payday toggle

The spending/committed-costs breakdown (`engines/insights.py::month_summary`, §6b) is
currently always calendar-month-bounded (`month: 'YYYY-MM'`). Add a toggle so it can
instead be bounded by the current payday-to-payday window — **reuse Phase 11's
`resolve_period()` for this**, don't reinvent period math; it already picks the
detected-or-manual payday window the same way `safe_to_spend` does, so the two
surfaces can never disagree about what "this period" means.

- Extend the relevant router (`routers/summary.py`, wherever `month_summary` is
  currently invoked) to accept a period-mode parameter (`period_mode: 'calendar' |
  'payday'`, default `calendar` to match today's behaviour exactly for anyone who
  hasn't touched the toggle) and, for `'payday'`, bound the category/transaction
  aggregation by `resolve_period()`'s window instead of calendar-month boundaries. The
  response should say which mode produced it (mirrors Phase 11's `payday_source`
  provenance pattern — don't return an ambiguous date range without saying how it was
  chosen).
- If no payday period can be resolved yet (still in setup, per `resolve_period`
  returning `None`), the `'payday'` mode should degrade to the existing `setup_missing`-
  style behaviour, not crash or silently fall back to calendar without saying so.
- Web: a small toggle control in `SpendingDetail.tsx` (or wherever the breakdown
  renders) switching between the two, persisted per-session at least (localStorage is
  fine, matches this app's existing lightweight-persistence patterns — check how
  `TransactionTable`'s own filter state or the theme toggle persist, for consistency).
  Copy should make clear which framing is showing ("this calendar month" vs "since
  your last payday").

## Hard constraints — same discipline as every prior phase, plus one deliberate exception

- Money integer pence everywhere, no floats in a money path — a PDF's £ text gets
  parsed straight to pence at the parse boundary, same as every other money entry
  point in this codebase (Starling/T212 float boundaries are the precedent).
- **The tax estimator itself still never guesses** (TAX.md §0) — this phase feeds it
  real extracted numbers, it does not relax the estimator's own missing-inputs gate or
  invent a number the documents don't actually contain.
- **The one deliberate, narrow exception to "unreviewed docs can't become tax data"**:
  today's invariant (`routers/tax.py`'s `document_unreviewed` gate) exists because an
  unconfirmed *guess* (the old single-regex amount parse) must never silently become a
  tax figure. This phase's auto-ledger path is different in kind, not just degree — a
  *structured, itemised* extraction that confidently matches a known, learned
  statement layout, from a document that passed the strict `is_confirmed_rent_statement`
  sender/subject check, for the one document type where the user has explicitly asked
  for this ("I'd rather you do this yourself, again, automation is the goal"). Keep
  the gate itself intact in code (`reviewed` still governs whether a document can be
  linked) — this phase's pipeline sets `reviewed=1` itself only at the moment it
  successfully creates the matching ledger rows, it doesn't remove or bypass the
  check for anything else. Any other document type, or a rent statement that doesn't
  parse confidently, goes through the review gate exactly as it does today.
- Read-only against Gmail/every bank/API — this phase adds a new *local* dependency
  (a PDF library) and new *local* parsing/backfill logic, no new external calls or
  write scopes.
- No real personal figures/names/amounts in anything committed — code, tests, docs,
  and the completion note all use synthetic placeholders; see the redaction note
  above. The one-off reclassification/backfill scripts run locally and report counts,
  not values.
- Run pytest + typecheck + vitest + build before committing; full redaction sweep
  (grep pass, same as every phase); update `docs/HANDOFF.md`'s state table, `docs/
  API.md` (§3c documents, §5 tax, §6a/§6b summary — new/changed fields), `docs/
  DATA_MODEL.md` if `TaxDocument`/`RentalLedgerEntry` gain columns (e.g. structured
  parsed-amount fields for audit — a new *nullable* column self-heals via
  `app/schema_sync.py`, no manual migration needed, confirm live that a restart picks
  it up cleanly); commit prefix `phase-12:`.
- **After this deploys, the orchestrator (not this phase) restarts `com.kakeibo.api`**
  — this phase touches `apps/server/`. State this prominently in the final report,
  per the standing CLAUDE.md gotcha (paid for three times already this project).

## Acceptance

- A synthetic fixture PDF (or extracted-text fixture, whichever the parser actually
  consumes) with placeholder rent/commission/maintenance figures produces correctly
  itemised, correctly-typed ledger rows via the parser, unit-tested without needing a
  real PDF library installed in CI if that's a constraint (check how `gmail.py`'s
  lazy-import + fake-service pattern handles this and mirror it if applicable).
- Running the backfill against the real local dev/prod DB turns the 103 real
  statements into real ledger rows (verified directly, by count and by the tax
  estimate no longer reading `gross_rents_minor: 0` — never by re-stating the actual
  figures anywhere committed).
- A rent statement that fails to parse confidently still lands in the review queue
  exactly as before, `reviewed=0`, no ledger rows created, no crash.
- The review queue no longer shows non-letting-agent/non-"Monthly Rental Statement "
  documents as rent-statement candidates; mortgage-interest-cert/insurance/other
  documents are untouched and still fully reviewable manually.
- `month_summary`'s calendar-mode output is byte-for-byte unchanged from before this
  phase for anyone not using the new toggle (default parameter, no regression).
  Payday-mode output uses the exact same period `resolve_period()` would give
  `safe_to_spend` for "today" — the two surfaces agree.
- Whatever `flat_share_minor`/`buffer_minor` audit conclusion is reached (automate,
  partially automate, or leave manual) is explicit and justified in the completion
  note, not silently decided.
