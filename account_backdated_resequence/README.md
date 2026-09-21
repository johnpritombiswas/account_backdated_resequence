# Backdated Journal Entry Auto-Resequencing

Odoo 18.0 module. Removes the manual "Resequence" step normally needed
after posting a backdated journal entry into a journal whose sequence
carries a date component (e.g. `MISC/2024/08/0001`).

## What it does

Odoo always numbers a newly-posted entry with the next available number in
its numbering period, regardless of where the entry actually falls
chronologically among entries already posted there. Backdating an entry
during mid-fiscal-year bookkeeping catch-up therefore leaves the sequence
numbers out of sync with the dates - Odoo doesn't block the post, but the
only built-in fix is Settings → Developer Mode → select entries → Actions
→ Resequence.

This module automates that fix. With the toggle enabled on a journal,
posting a backdated entry:

1. Posts normally - never blocked, never fails.
2. Checks whether the entry's numbering period is now out of chronological
   order (some entry with a lower number has a later date, or vice versa).
3. If so, reorders just that period using Odoo's own
   `account.resequence.wizard` (the same code the manual Actions →
   Resequence menu calls) - no renumbering logic is reimplemented.
4. Logs a chatter message on every renamed entry: *"Automatically
   resequenced from X to Y due to backdated posting."*

## The toggle

**Accounting → Configuration → Journals → (a journal) → Advanced Settings
→ "Allow Auto-Resequencing on Backdated Entries"**, next to "Secure Posted
Entries with Hash".

- Off by default, opt-in per journal.
- Only applies to journals whose sequence includes a year and/or month
  component. Flat numbering (no date in the format) is never affected.

## Audit trail

Every automatic renumbering is logged as a chatter message on the affected
journal entry (`Automatically resequenced from X to Y due to backdated
posting`), so there's a permanent, visible record of what changed and why
- the same place all of an entry's other audit history lives.

## Hash-lock safety limitation

If "Secure Posted Entries with Hash" is enabled on the journal and any of
the entries that would need renumbering are already hash-secured
(`inalterable_hash` set), automatic resequencing is **skipped entirely**
for that group - inserting a number into an already-hashed chain would
break the audit chain the hash exists to protect. The backdated entry
still posts successfully; a chatter warning explains why it wasn't
reordered and points to the standard manual process (Developer Mode →
select entries → Actions → Resequence) as the documented fallback for that
case.

## Concurrency

Before computing a resequencing plan, the module takes a row lock
(`SELECT ... FOR UPDATE`) on the candidate journal/period so two users
posting backdated entries into the same journal at the same time can't
produce duplicate or skipped sequence numbers. Actual number uniqueness is
still guaranteed the same way it always is in Odoo - by `sequence.mixin`'s
own locked-increment mechanism over a partial unique index.
