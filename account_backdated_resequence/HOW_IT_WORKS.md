# How `account_backdated_resequence` works

## Structure

```
account_backdated_resequence/
├── models/account_journal.py         # adds the on/off toggle
├── models/account_move.py            # ALL the logic
├── views/account_journal_views.xml   # shows the toggle on the Journal form
├── views/account_move_menus.xml      # Accounting -> Backdated Journal Entries
└── tests/                            # 7 tests
```

## Logic (`models/account_move.py`)

The module wraps Odoo's `_post()`. Odoo posts and numbers the entry as usual,
and the module then checks whether the numbers still match the dates.

1. **Post normally.** `super()._post()` runs first, so posting never fails
   because of this module.
2. **Gate.** Continue only if the journal toggle is on **or** the entry was
   posted from the *Backdated Journal Entries* menu (the menu sets a
   `backdated_resequence` context flag). The entry must also have a
   date-based number; flat numbers such as `INV/0007` are skipped.
3. **Lock.** `SELECT ... FOR UPDATE` on that journal and month, so two users
   posting at the same time cannot both reorder it. If PostgreSQL reports a
   serialization failure, Odoo's `retrying()` re-runs the whole transaction.
4. **Detect disorder.** Take the other posted entries with the same sequence
   prefix (for example `MISC/26-27/08/`). The entry is out of order if some
   entry has a lower number but a later date. If none does, stop.
5. **Hash check.** If any affected entry has an `inalterable_hash`, do not
   renumber. Post a chatter warning on the entry and stop.
6. **Fix.** Create Odoo's own `account.resequence.wizard` with
   `ordering='date'` and run `resequence()`. No numbering code is duplicated.
7. **Audit.** Each renamed entry gets a chatter note: *"Automatically
   resequenced from X to Y due to backdated posting."*

## Example

Fiscal year ends June 30. Entries are posted in this order:

| Step | Entry date | Odoo assigns | After the module |
|---|---|---|---|
| 1 | Aug 20 | `MISC/26-27/08/0001` | `0001` |
| 2 | Aug 10 | `MISC/26-27/08/0002` | **`0001`** |
| 3 | (the Aug 20 entry) | | **`0002`** (renamed, with a chatter note) |

At step 2 the module sees that entry `0001` has a later date (Aug 20) than the
new one (Aug 10), so it reorders both by date. With the toggle off, and outside
the menu, step 2 would stay `0002`, out of date order.

## Limits

- **Per numbering period only.** It reorders within one prefix, i.e. one month
  for `MISC/26-27/08/xxxx`-style numbers, because the counter restarts monthly.
- **Assumes earlier entries were already in date order.** If the existing
  numbering was already scrambled, the reorder could collide with a number
  outside the affected set. This case is not tested.
- **Does not fix a fiscal-year mismatch.** The error *"The Date ... isn't
  aligned with the existing sequence number"* appears when the company's
  fiscal-year end (Accounting > Configuration > Settings > Fiscal Year) does not
  match the journal's number style (e.g. `26-27` needs a June 30 year end).
  Odoo raises it in its own posting check, before this module runs.
- **Hash-locked entries are never renumbered.** The entry still posts; a
  warning is logged instead.
