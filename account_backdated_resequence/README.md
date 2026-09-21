# Backdated Journal Entry Auto-Resequencing

Odoo 18.0 module. Removes the manual "Resequence" step normally needed
after posting a backdated journal entry into a journal whose sequence
carries a date component (e.g. `MISC/2024/08/0001`).

## What it does

Odoo always numbers a newly-posted entry with the next available number in
its numbering period, regardless of where the entry actually falls
chronologically among entries already posted there. Backdating an entry
during mid-fiscal-year bookkeeping catch-up therefore leaves the sequence
numbers out of sync with the dates. Usually this doesn't block the post,
but the only built-in fix is Settings → Developer Mode → select entries →
Actions → Resequence.

There's a sharper version of the same root cause that *does* block the
post outright: Odoo's own lookup for "what name should this entry get"
can find an *existing* entry whose date happens to fall in the new
entry's period, and copies that entry's year/month digits straight out of
its name string rather than computing them from the date. If that
existing entry's name doesn't actually match its own date (see
[HOW_IT_WORKS.md](HOW_IT_WORKS.md) for exactly how that happens), the new
entry inherits the same wrong prefix - and Odoo's own validation then
refuses to save it: *"The Date ... isn't aligned with the existing
sequence number ... Clear the sequence number to proceed."* This module
fixes that too, unconditionally (see below).

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

## Wrong-prefix correction (always on)

Unlike the reordering feature above, this part isn't opt-in and doesn't
need the toggle or the menu - it runs on every post, in every journal,
because it's a data-integrity fix, not a convenience:

1. The post always succeeds - the constraint that would otherwise block
   it ("The Date ... isn't aligned with the existing sequence number
   ...") is bypassed just long enough for Odoo to assign a name.
2. Right after, the module checks that name's year/month against the
   entry's own Accounting Date.
3. If they don't match, it renames the entry into the correct period,
   right after the last existing entry that's actually in that period -
   and logs a chatter message: *"Corrected sequence: this entry's date
   (...) does not match the ... numbering period assigned to it - renamed
   to ..."*.
4. A hash-secured entry that turns out to need this can't be renamed (see
   Hash-lock safety below) - it posts with the wrong name and a chatter
   warning instead, the same as the reordering feature does.

### Accounting > Repair Sequence Prefixes

For entries that already exist with a wrong prefix from before the module
was installed: **Accounting → Repair Sequence Prefixes** (Accountant/
Advisor access) scans posted entries - in one journal or every journal -
and fixes any mismatches it finds, reporting exactly what it renamed.
Hash-secured entries it can't fix are left alone; nothing else in the
database is touched.

## The menu: Accounting > Backdated Journal Entries

Prefer not to switch on a whole journal? **Accounting → Backdated Journal
Entries** opens the journal entries list (manual entries only). Anything you
create and post from there gets the same automatic resequencing on *any*
journal - no journal setting needed. Under the hood the menu's action sets a
`backdated_resequence` context key that the posting logic checks. Hash-lock
safety, the date-component check and the audit messages behave exactly as
described below.

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

See [HOW_IT_WORKS.md](HOW_IT_WORKS.md) for the structure and the step-by-step logic, with an example.
