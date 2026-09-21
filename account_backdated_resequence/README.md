# Backdated Journal Entry Auto-Resequencing

Odoo 18.0 module. Removes the manual "Resequence" step normally needed
after posting a backdated journal entry into a journal whose sequence
carries a date component (e.g. `MISC/2024/08/0001`) - automatically, on
every journal, with nothing to configure.

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
sequence number ... Clear the sequence number to proceed."*

This module fixes both, unconditionally, on every journal:

1. **Post always succeeds.** The constraint that would otherwise block it
   is bypassed just long enough for Odoo to assign a name.
2. **Wrong prefix gets corrected.** Right after, the module checks that
   name's year/month against the entry's own Accounting Date. If they
   don't match, it renames the entry into the correct period - logging a
   chatter message: *"Corrected sequence: this entry's date (...) does not
   match the ... numbering period assigned to it - renamed to ..."*.
3. **Chronological order gets fixed.** The entry's numbering period is
   then checked for date order (some entry with a lower number has a later
   date, or vice versa). If it's out of order, that period is reordered
   using Odoo's own `account.resequence.wizard` (the same code the manual
   Actions → Resequence menu calls) - no renumbering logic is
   reimplemented. Logs a chatter message on every renamed entry:
   *"Automatically resequenced from X to Y due to backdated posting."*
4. A hash-secured entry that turns out to need either fix can't be renamed
   (see Hash-lock safety below) - it posts with the wrong name and a
   chatter warning instead.

Nothing to switch on: this applies to every journal whose sequence
includes a year and/or month component. Flat numbering (no date in the
format) is never affected either way.

## Accounting > Repair Sequence Prefixes

For entries that already exist with a wrong prefix from before the module
was installed: **Accounting → Repair Sequence Prefixes** (Accountant/
Advisor access) scans posted entries - in one journal or every journal -
and fixes any mismatches it finds, reporting exactly what it renamed.
Hash-secured entries it can't fix are left alone; nothing else in the
database is touched.

## Accounting > Backdated Journal Entries

A plain filtered shortcut onto Journal Entries (Accounting → Backdated
Journal Entries). It behaves no differently than the standard Journal
Entries screen - both fixes above apply everywhere regardless of which one
you use - it just exists as a convenient, purpose-labelled place to work
from when you know you're catching up on backdated entries.

## Audit trail

Every automatic correction and renumbering is logged as a chatter message
on the affected journal entry, so there's a permanent, visible record of
what changed and why - the same place all of an entry's other audit
history lives.

## Hash-lock safety limitation

If "Secure Posted Entries with Hash" is enabled on the journal and an
entry that would need correcting or renumbering is already hash-secured
(`inalterable_hash` set), that fix is **skipped entirely** for it -
inserting a number, or renaming, an already-hashed entry would break the
audit chain the hash exists to protect. The entry still posts
successfully; a chatter warning explains why it wasn't fixed and points to
the standard manual process (Developer Mode → select entries → Actions →
Resequence) as the documented fallback for that case.

## Concurrency

Before computing a resequencing plan, the module takes a row lock
(`SELECT ... FOR UPDATE`) on the candidate journal/period so two users
posting backdated entries into the same journal at the same time can't
produce duplicate or skipped sequence numbers. Actual number uniqueness is
still guaranteed the same way it always is in Odoo - by `sequence.mixin`'s
own locked-increment mechanism over a partial unique index.

See [HOW_IT_WORKS.md](HOW_IT_WORKS.md) for the structure and the step-by-step logic, with an example.
