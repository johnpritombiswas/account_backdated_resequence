# How `account_backdated_resequence` works

## Structure

```
account_backdated_resequence/
├── models/account_move.py                              # ALL the sequencing logic
├── wizard/repair_wrong_sequence_prefix_wizard.py        # Accounting > Repair Sequence Prefixes
├── security/ir.model.access.csv                         # access for the wizard
├── views/account_move_menus.xml                         # Accounting -> Backdated Journal Entries
└── tests/                                                # 10 tests
```

## Two separate problems, two separate fixes

Both live in `models/account_move.py`, both trigger from the same `_post()`
override, both run unconditionally on every journal, every post - neither
needs any configuration:

1. **Wrong-prefix correction** (`_correct_wrong_sequence_prefix`) - fixes a
   name whose year/month doesn't match its own date. See below for why
   this can even happen.
2. **Chronological reordering** (`_auto_resequence_backdated`) - fixes
   numbers that are merely out of date order within an otherwise correct
   period. Skipped for flat numbers such as `INV/0007` (no date component
   to reorder by).

### 1. Wrong-prefix correction

Odoo's own sequence lookup, when assigning a new entry's name, searches for
an *existing* entry whose `date` falls in the new entry's period, and
copies that entry's year/month digits **literally out of its name
string** - not computed from the date. If that existing entry's name
doesn't actually match its own date (a manually-set placeholder, a draft
with a stale number, historical data that predates validation), the new
entry inherits the exact same wrong digits.

Left alone, Odoo's own `_constrains_date_sequence` then refuses to save
that mismatch: *"The Date ... isn't aligned with the existing sequence
number ... Clear the sequence number to proceed."* - a hard block, not a
silent corruption.

1. **Bypass, just long enough to let a name be assigned.** `_post()` posts
   with that one constraint turned off for the entries it's posting -
   without this, the scenario below never even gets a name to check.
2. **Check.** For every posted move with a date-based sequence, recompute
   what its prefix *should* be, purely from its own date, and compare to
   what was actually assigned.
3. **Hash check.** If the entry is already hash-secured (see Hash-lock
   safety below), it can't be renamed - warn instead, stop.
4. **Fix.** Rename it, right after the last existing entry that's
   genuinely in that period.
5. **Audit.** Chatter note: *"Corrected sequence: this entry's date (...)
   does not match the ... numbering period assigned to it - renamed to
   ..."*.

### 2. Chronological reordering

1. **Lock.** `SELECT ... FOR UPDATE` on that journal and period, so two
   users posting at the same time cannot both reorder it. If PostgreSQL
   reports a serialization failure, Odoo's `retrying()` re-runs the whole
   transaction.
2. **Detect disorder.** Take the other posted entries with the same
   sequence prefix (for example `MISC/26-27/08/`). The entry is out of
   order if some entry has a lower number but a later date. If none does,
   stop.
3. **Full scope, not just the disordered ones.** The set handed to the
   wizard is *every* sibling sharing the prefix, not only the ones
   pairwise out of order with the move being posted. `account.resequence.
   wizard` treats its input as a closed set and reassigns it sequential
   numbers as if those were the only entries in the prefix - leaving some
   sibling out (even one that's individually "in order") can leave it
   still holding a number the wizard just reassigned to someone else,
   raising a real `UniqueViolation` ("Another entry with the same name
   already exists"). Handing it everyone keeps the numbering space
   complete, so nothing outside the set can collide with a number now
   assigned inside it.
4. **Hash check.** If any affected entry has an `inalterable_hash`, do not
   renumber. Post a chatter warning on the entry and stop.
5. **Fix.** Create Odoo's own `account.resequence.wizard` with
   `ordering='date'` and run `resequence()`. No numbering code is
   duplicated.
6. **Audit.** Each renamed entry gets a chatter note: *"Automatically
   resequenced from X to Y due to backdated posting."*

### Repairing existing history

The wrong-prefix fix above only touches the entry actually being posted.
For entries that already have a wrong prefix from before the module was
installed, **Accounting → Repair Sequence Prefixes**
(`wizard/repair_wrong_sequence_prefix_wizard.py`) scans posted entries -
one journal or all of them - and runs the same correction logic across
all of them at once, reporting exactly what it renamed.

## Example

Fiscal year ends June 30. Entries are posted in this order:

| Step | Entry date | Odoo assigns | After the module |
|---|---|---|---|
| 1 | Aug 20 | `MISC/26-27/08/0001` | `0001` |
| 2 | Aug 10 | `MISC/26-27/08/0002` | **`0001`** |
| 3 | (the Aug 20 entry) | | **`0002`** (renamed, with a chatter note) |

At step 2 the module sees that entry `0001` has a later date (Aug 20) than the
new one (Aug 10), so it reorders both by date - automatically, on every
journal, nothing to turn on first.

## Limits

- **Reordering is per numbering period only.** It reorders within one
  prefix, i.e. one month for `MISC/26-27/08/xxxx`-style numbers, because
  the counter restarts monthly.
- **Doesn't fix a genuine fiscal-year misconfiguration.** The same error
  text - *"The Date ... isn't aligned with the existing sequence number"*
  - can also appear when the company's fiscal-year end (Accounting >
  Configuration > Settings > Fiscal Year) simply doesn't match the
  journal's number style at all (e.g. `26-27` needs a June 30 year end,
  not December 31). That's a real configuration problem, not a wrong
  reference row, and this module can't tell the two apart from the error
  alone - if the wrong-prefix fix runs and still can't make the numbers
  line up, check the fiscal-year setting first.
- **Hash-locked entries are never renumbered**, by either fix. They post
  with whatever name Odoo assigned; a chatter warning explains why and
  points to the manual Resequence wizard.
