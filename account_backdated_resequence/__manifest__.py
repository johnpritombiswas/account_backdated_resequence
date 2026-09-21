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

This module removes that manual step, on every journal, automatically -
nothing to configure, nothing to switch on. Posting a backdated entry:

* Always succeeds - nothing is blocked, even when Odoo's own sequence
  numbering would otherwise hard-block it (see the sharper bug below).
* Gets checked against every other entry in its numbering period: if
  it's out of chronological order, that period is reordered into date
  order using Odoo's own built-in Resequence wizard under the hood - no
  renumbering logic is reimplemented.
* Logs a chatter message on every renamed entry: "Automatically
  resequenced from X to Y due to backdated posting" - a visible audit
  trail of every automatic renumbering.

Flat-numbered journals (no year/month in the sequence) are never
touched, since there's no date-based order to maintain.

Also fixes a sharper, related core Odoo bug: when a brand-new entry's date
falls in the same period as an *existing* entry, Odoo copies that
existing entry's year/month digits straight out of its name rather than
computing them from the date. If that existing entry's name was ever
wrong - typically from a data migration that set the entry number
directly - every later entry in that period silently inherits the same
wrong year/month, entry after entry (e.g. an entry dated in August ending
up named .../09/0023). This module checks every posted entry's name
against its own date and corrects any mismatch automatically, on every
journal - this is a data-integrity fix, not an opt-in feature. The
Accounting app's Accounting tab gets a "Repair Sequence Prefixes" menu
(Accountant/Advisor access) to scan and fix existing history in one click.

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
    "version": "19.0.1.0.0",
    "category": "Accounting/Accounting",
    "license": "LGPL-3",
    "author": "DotBD Solutions",
    "company": "Dot BD Solutions Limited",
    "maintainer": "John Pritom Biswas",
    "website": "https://dotbdsolutions.com",
    "support": "info@dotbdsolutions.com",
    "depends": ["account"],
    "data": [
        "security/ir.model.access.csv",
        "views/account_move_menus.xml",
        "wizard/repair_wrong_sequence_prefix_wizard_views.xml",
    ],
    "images": ["static/description/icon.png"],
    "installable": True,
    "application": False,
    "auto_install": False,
}
