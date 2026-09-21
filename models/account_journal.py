# -*- coding: utf-8 -*-
from odoo import fields, models


class AccountJournal(models.Model):
    _inherit = 'account.journal'

    auto_resequence_backdated = fields.Boolean(
        string="Allow Auto-Resequencing on Backdated Entries",
        default=False,
        help="When a journal entry is posted with an Accounting Date that "
             "falls earlier than entries already posted in this journal's "
             "current numbering period, automatically reorder the affected "
             "entries' numbers into chronological order right after "
             "posting - no manual Resequence action needed.\n\n"
             "Only applies to journals whose sequence includes a year "
             "and/or month component (e.g. MISC/2024/08/0001); flat "
             "numbering is never affected.\n\n"
             "If any of the affected entries are already secured by a "
             "posting hash (Secure Posted Entries with Hash), the audit "
             "chain cannot be broken: the new entry still posts normally, "
             "but automatic resequencing is skipped and a warning is "
             "logged on the entry instead.",
    )
