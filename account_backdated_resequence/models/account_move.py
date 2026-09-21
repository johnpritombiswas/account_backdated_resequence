# -*- coding: utf-8 -*-
import json

from odoo import Command, _, models
from odoo.tools.misc import format_date


class AccountMove(models.Model):
    _inherit = 'account.move'

    def _post(self, soft=True):
        # EXTENDS account
        posted = super()._post(soft=soft)
        posted._auto_resequence_backdated()
        return posted

    def _auto_resequence_backdated(self):
        """After posting, silently reorder entries whose numbering is out of
        chronological sync because this move was backdated - only for
        journals that opted in (`auto_resequence_backdated`) or entries posted
        through Accounting > Backdated Journal Entries (which sets the
        `backdated_resequence` context key), and whose sequence actually
        carries a date component.
        """
        via_menu = self.env.context.get('backdated_resequence')
        for move in self:
            journal = move.journal_id
            if not (journal.auto_resequence_backdated or via_menu):
                continue
            if not move.name or move.name == '/':
                continue
            if move._deduce_sequence_number_reset(move.name) == 'never':
                # Flat numbering (no year/month in the format): nothing to reorder.
                continue
            move._auto_resequence_backdated_one()

    def _auto_resequence_backdated_one(self):
        self.ensure_one()
        journal = self.journal_id

        # Lock the candidate group first so two transactions backdating into
        # the same journal/period can't compute conflicting resequence plans
        # at once. Per-number uniqueness itself is already guaranteed by
        # sequence.mixin's own _locked_increment/unique-index mechanism.
        # A PostgreSQL SerializationFailure here is expected under concurrency
        # (REPEATABLE READ snapshot older than another transaction's commit):
        # Odoo's request/cron dispatch (odoo.service.model.retrying) rolls back
        # and retries the whole transaction. Don't log it as an SQL error, the
        # same way sequence.mixin._locked_increment doesn't for its own races.
        self.env.cr.execute(
            "SELECT id FROM account_move WHERE journal_id = %s AND sequence_prefix = %s FOR UPDATE",
            (journal.id, self.sequence_prefix),
            log_exceptions=False,
        )

        domain = [
            ('journal_id', '=', journal.id),
            ('sequence_prefix', '=', self.sequence_prefix),
            ('id', '!=', self.id),
            ('state', '=', 'posted'),
            ('name', 'not in', ('/', False, '')),
        ]
        # Mirror account.move's own sub-chain split (refunds / payments share
        # a journal+prefix with a different numbering chain) so we never hand
        # the wizard a mix it would itself refuse (see
        # account.resequence.wizard.default_get).
        if journal.refund_sequence:
            refund_types = ('out_refund', 'in_refund')
            domain += [('move_type', 'in' if self.move_type in refund_types else 'not in', refund_types)]
        if journal.payment_sequence:
            is_payment = bool(self.origin_payment_id)
            domain += [('origin_payment_id', '!=' if is_payment else '=', False)]

        siblings = self.search(domain)
        if not siblings:
            return

        out_of_order = siblings.filtered(
            lambda s: (s.sequence_number < self.sequence_number and s.date > self.date)
            or (s.sequence_number > self.sequence_number and s.date < self.date)
        )
        if not out_of_order:
            return

        scope = out_of_order | self
        if scope.filtered('inalterable_hash'):
            self.message_post(body=_(
                "This entry was posted with a backdated Accounting Date (%(date)s), which is "
                "out of chronological order with existing entries in this journal's "
                "%(prefix)s numbering period. Automatic resequencing was skipped because one "
                "or more of the affected entries are already secured by a posting hash - "
                "inserting it automatically would break the audit chain. Use Settings > "
                "Developer Mode > select the affected entries > Actions > Resequence to "
                "reorder them manually if needed.",
                date=format_date(self.env, self.date),
                prefix=self.sequence_prefix,
            ))
            return

        # account.resequence.wizard.first_name is a required, stored compute
        # field that only self-computes reliably through the UI/Form flow.
        # Pass it explicitly, reproducing exactly what its own
        # _compute_first_name would derive (the lowest current name in the
        # scope), so a plain ORM create() here behaves the same as opening
        # the wizard from Actions > Resequence would.
        wizard = self.env['account.resequence.wizard'].create({
            'move_ids': [Command.set(scope.ids)],
            'ordering': 'date',
            'first_name': min(scope.mapped('name')),
        })
        new_values = json.loads(wizard.new_values)
        renamed = {
            int(move_id): (values['current_name'], values['new_by_date'])
            for move_id, values in new_values.items()
            if values['current_name'] != values['new_by_date']
        }
        wizard.resequence()

        for move_id, (old_name, new_name) in renamed.items():
            self.browse(move_id).message_post(body=_(
                "Automatically resequenced from %(old)s to %(new)s due to backdated posting.",
                old=old_name,
                new=new_name,
            ))
