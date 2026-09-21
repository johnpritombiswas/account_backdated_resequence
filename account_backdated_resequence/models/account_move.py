# -*- coding: utf-8 -*-
import json
import re

from odoo import Command, _, models
from odoo.tools.misc import format_date


class AccountMove(models.Model):
    _inherit = 'account.move'

    def _post(self, soft=True):
        # EXTENDS account
        # Core's own sequence assignment can compute a name that mismatches
        # the move's own date (see `_correct_wrong_sequence_prefix_one` for
        # exactly why) - which would otherwise hard-block the post via
        # sequence.mixin._constrains_date_sequence: "The Date ... isn't
        # aligned with the existing sequence number ...". That is the error
        # a genuinely backdated post can hit even with everything else
        # configured correctly. We bypass that one constraint here so the
        # post always succeeds, then immediately detect and correct any
        # such mismatch ourselves - the bypass never leaves it silently
        # persisted (a hash-locked entry that can't be corrected gets a
        # chatter warning instead, same as the reordering logic below).
        posted = super(AccountMove, self.with_context(skip_sequence_date_check=True))._post(soft=soft)
        # Correcting an entry whose name carries the wrong year/month for its
        # own date is not a "nice to have" like the reordering below - it is
        # fixing a data-integrity bug in core Odoo's own numbering, so it
        # runs unconditionally, on every journal, not just opted-in ones.
        posted._correct_wrong_sequence_prefix()
        posted._auto_resequence_backdated()
        return posted

    def _must_check_constrains_date_sequence(self):
        # EXTENDS account (which extends sequence.mixin)
        if self.env.context.get('skip_sequence_date_check'):
            return False
        return super()._must_check_constrains_date_sequence()

    def _correct_wrong_sequence_prefix(self):
        """Detect and fix entries whose assigned name carries a year/month
        that does not match their own Accounting Date.

        This happens because of a sharp edge in core Odoo's own sequence
        mixin: when a brand-new entry's date falls inside the date range of
        an *existing* row (`date BETWEEN period_start AND period_end`), Odoo
        reuses that existing row's name to detect the numbering pattern, and
        copies its year/month digits *literally out of the name string* -
        not from the date. If that existing row's name was itself already
        wrong (e.g. from a data migration/import that set `name` directly,
        or from a first occurrence of this same bug), the mistake is copied
        forward onto every new entry in that period from then on, one after
        another - MISC/26-27/09/0023 dated 17 August being a textbook
        example: some earlier August-dated row already carried a
        `.../09/....` name, so every later August posting inherited "09".

        Odoo's core code never checks this itself; it only guards against a
        *manually typed* name not matching its date, not one it computed and
        wrote itself.

        For every move whose sequence carries a date component, this
        recomputes what its prefix should be purely from its own date
        (ignoring whatever reference row core actually used), and if that
        differs from what was assigned, renames it into the correct group,
        immediately after the last existing entry that already carries the
        correct prefix.
        """
        for move in self:
            if not move.name or move.name == '/':
                continue
            if move._deduce_sequence_number_reset(move.name) == 'never':
                continue
            move._correct_wrong_sequence_prefix_one()

    def _correct_wrong_sequence_prefix_one(self):
        self.ensure_one()
        journal = self.journal_id
        reset = self._deduce_sequence_number_reset(self.name)
        format_string, format_values = self._get_sequence_format_param(self.name)
        date_start, date_end, forced_year_start, forced_year_end = self._get_sequence_date_range(reset)

        expected = dict(format_values)
        expected['year'] = self._truncate_year_to_length(forced_year_start or date_start.year, format_values['year_length'])
        expected['year_end'] = self._truncate_year_to_length(forced_year_end or date_end.year, format_values['year_end_length'])
        expected['month'] = self.date.month
        expected['seq'] = 0
        expected_name = format_string.format(**expected)

        # sequence_prefix is "everything before the numeric sequence", the
        # same slice `_compute_split_sequence` uses.
        regex = self._make_regex_non_capturing(self._sequence_fixed_regex.replace(r"?P<seq>", ""))
        matching = re.match(regex, expected_name)
        expected_prefix = expected_name[:matching.start(1)]

        if expected_prefix == self.sequence_prefix:
            return  # already correct, nothing to do

        # Lock the correct prefix group before deciding the next number, so
        # two transactions correcting into the same new group can't compute
        # conflicting numbers. As with the row lock below in
        # `_auto_resequence_backdated_one`, this locks nothing when the
        # group is currently empty - the first correction into a brand new
        # period relies on sequence.mixin's own unique-index protection.
        self.env.cr.execute(
            "SELECT id FROM account_move WHERE journal_id = %s AND sequence_prefix = %s FOR UPDATE",
            (journal.id, expected_prefix),
            log_exceptions=False,
        )

        if self.inalterable_hash:
            self.message_post(body=_(
                "This entry's name (%(name)s) does not match its Accounting Date (%(date)s) - "
                "it should be in the %(expected_prefix)s numbering period, not "
                "%(actual_prefix)s. It could not be corrected automatically because it is "
                "already secured by a posting hash. Use Settings > Developer Mode > select the "
                "entry > Actions > Resequence, or rename it manually, after checking with "
                "whoever manages the audit trail.",
                name=self.name,
                date=format_date(self.env, self.date),
                expected_prefix=expected_prefix,
                actual_prefix=self.sequence_prefix,
            ))
            return

        last_domain = [
            ('journal_id', '=', journal.id),
            ('sequence_prefix', '=', expected_prefix),
            ('state', '=', 'posted'),
            ('id', '!=', self.id),
        ]
        # Same sub-chain split as `_auto_resequence_backdated_one`: refunds
        # and payments number separately even when they'd otherwise share a
        # prefix, so "last" must respect that split too.
        if journal.refund_sequence:
            refund_types = ('out_refund', 'in_refund')
            last_domain += [('move_type', 'in' if self.move_type in refund_types else 'not in', refund_types)]
        if journal.payment_sequence:
            is_payment = bool(self.origin_payment_id)
            last_domain += [('origin_payment_id', '!=' if is_payment else '=', False)]
        last = self.search(last_domain, order='sequence_number desc', limit=1)
        next_seq = (last.sequence_number + 1) if last else 1

        corrected = dict(expected)
        corrected['seq'] = next_seq
        new_name = format_string.format(**corrected)

        old_name = self.name
        self.name = new_name
        self.message_post(body=_(
            "Corrected sequence: this entry's date (%(date)s) does not match the %(old)s "
            "numbering period assigned to it - renamed to %(new)s. This happens when Odoo's "
            "own sequence numbering copies a wrong year/month from an earlier entry; see "
            "the account_backdated_resequence module's README for the mechanism.",
            date=format_date(self.env, self.date),
            old=old_name,
            new=new_name,
        ))

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

        # The wizard treats move_ids as a *closed* set: it reassigns them
        # sequential numbers starting from first_name, as if they were the
        # only entries in this prefix. Scoping to just the pairwise
        # out-of-order entries (plus self) would leave any in-order sibling
        # that sits *inside* that numeric range untouched but still holding
        # its old number - which the wizard would then reissue to a
        # different entry, raising "Another entry with the same name
        # already exists." Handing it every sibling in the prefix keeps the
        # numbering space complete, so nothing outside the set can collide
        # with a number now assigned inside it.
        scope = siblings | self
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
