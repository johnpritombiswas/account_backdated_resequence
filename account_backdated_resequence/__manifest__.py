{
    "name": "Backdated Journal Entry Auto-Resequencing",
    "summary": "Automatically reorder date-based journal entry numbers after a backdated post",
    "description": """
Backdated Journal Entry Auto-Resequencing
==========================================

Journals whose sequence embeds a date component (e.g. MISC/2024/08/0001)
always number a new entry with the next available number in its period -
regardless of where that entry actually falls chronologically among
entries already posted there. Catching up on bookkeeping by entering
entries out of date order therefore leaves the numbering silently out of
sync with the dates, fixable today only through Settings > Developer Mode
> select entries > Actions > Resequence.

This module removes that manual step. Enable "Allow Auto-Resequencing on
Backdated Entries" on a journal (Accounting > Configuration > Journals >
Advanced Settings, next to "Secure Posted Entries with Hash") and, from
then on, posting a backdated entry into that journal automatically:

* Posts the entry normally - it always succeeds, nothing is blocked.
* Detects whether the entry's period (its year/month numbering group) is
  now out of chronological order.
* If so, reorders just that period's entries into date order, using
  Odoo's own built-in Resequence wizard under the hood - no renumbering
  logic is reimplemented.
* Logs a chatter message on every renamed entry: "Automatically
  resequenced from X to Y due to backdated posting" - a visible audit
  trail of every automatic renumbering.

Prefer not to switch a whole journal? Use Accounting > Backdated Journal
Entries instead: entries created and posted from that menu get the same
automatic resequencing on any journal, with no journal setting needed.

Off by default and opt-in per journal, so journals where strict manual
control is wanted are never affected. Flat-numbered journals (no
year/month in the sequence) are never touched either way.

Safety and integrity:

* If any of the affected entries are already secured by a posting hash
  (journal setting "Secure Posted Entries with Hash"), the audit chain
  cannot be broken. The backdated entry still posts normally, but
  automatic resequencing is skipped and a clear warning is logged on the
  entry instead, pointing to the manual Resequence wizard as the
  documented fallback.
* Concurrent backdated posting into the same journal/period is
  serialized with a row lock before resequencing, so two users posting
  at the same time can't produce duplicate or skipped numbers.

See README.md in this module for more detail.
""",
    "version": "18.0.1.1.0",
    "category": "Accounting/Accounting",
    "license": "LGPL-3",
    "author": "DotBD Solutions",
    "company": "Dot BD Solutions Limited",
    "maintainer": "John Pritom Biswas",
    "website": "https://dotbdsolutions.com",
    "support": "info@dotbdsolutions.com",
    "depends": ["account"],
    "data": [
        "views/account_journal_views.xml",
        "views/account_move_menus.xml",
    ],
    "images": ["static/description/icon.png"],
    "installable": True,
    "application": False,
    "auto_install": False,
}
