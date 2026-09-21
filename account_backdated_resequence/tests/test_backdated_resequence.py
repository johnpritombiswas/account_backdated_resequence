# -*- coding: utf-8 -*-
import functools

from odoo import api, fields, SUPERUSER_ID
from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.service.model import retrying
from odoo.tests import tagged, TransactionCase


@tagged('post_install', '-at_install')
class TestBackdatedResequenceCommon(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.journal = cls.env['account.journal'].create({
            'name': 'Backdated Resequence Test Journal',
            'code': 'BDR',
            'type': 'general',
            'auto_resequence_backdated': True,
        })

    def _create_move(self, date):
        move = self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': self.journal.id,
            'date': date,
            'line_ids': [(0, 0, {
                'name': 'line',
                'account_id': self.company_data['default_account_revenue'].id,
            })],
        })
        return move

    def _corrupt_move_name(self, move, new_name):
        """Simulate the core Odoo bug this module guards against: a posted
        move whose name carries the wrong year/month for its own date,
        written the same low-level way sequence.mixin._locked_increment
        writes a real sequence number - a raw SQL UPDATE that bypasses the
        ORM's date/sequence constraint entirely - with the stored
        sequence_prefix/sequence_number split fields brought back in sync
        afterwards, exactly like sequence.mixin._set_next_sequence does
        right after its own raw SQL write.
        """
        self.env.cr.execute("UPDATE account_move SET name = %s WHERE id = %s", (new_name, move.id))
        move.invalidate_recordset(['name'])
        move._compute_split_sequence()
        move.flush_recordset(['sequence_prefix', 'sequence_number'])


@tagged('post_install', '-at_install')
class TestBackdatedResequence(TestBackdatedResequenceCommon):
    def test_normal_in_order_posting_is_unaffected(self):
        """Posting strictly in chronological order never triggers a resequence."""
        move1 = self._create_move('2024-08-05')
        move1.action_post()
        move2 = self._create_move('2024-08-10')
        move2.action_post()

        self.assertEqual(move1.name, 'BDR/2024/08/0001')
        self.assertEqual(move2.name, 'BDR/2024/08/0002')
        self.assertFalse(move2.message_ids.filtered(lambda m: 'resequenced' in (m.body or '')))

    def test_backdated_posting_auto_resequences(self):
        """A backdated post reorders the affected period into chronological order."""
        move1 = self._create_move('2024-08-20')
        move1.action_post()
        self.assertEqual(move1.name, 'BDR/2024/08/0001')

        # Backdated: earlier date than move1, but would naturally get the next number.
        move2 = self._create_move('2024-08-10')
        move2.action_post()

        move1.invalidate_recordset(['name'])
        move2.invalidate_recordset(['name'])
        self.assertEqual(move2.name, 'BDR/2024/08/0001')
        self.assertEqual(move1.name, 'BDR/2024/08/0002')

        resequence_msg = move1.message_ids.filtered(lambda m: 'Automatically resequenced' in (m.body or ''))
        self.assertTrue(resequence_msg, "Expected an audit chatter message documenting the resequencing.")

    def test_disabled_journal_is_unaffected(self):
        """The toggle is opt-in: with it off, backdated posting is left as-is."""
        self.journal.auto_resequence_backdated = False
        move1 = self._create_move('2024-08-20')
        move1.action_post()
        move2 = self._create_move('2024-08-10')
        move2.action_post()

        move1.invalidate_recordset(['name'])
        self.assertEqual(move1.name, 'BDR/2024/08/0001')
        self.assertEqual(move2.name, 'BDR/2024/08/0002')

    def test_backdated_posting_into_hash_locked_journal_warns_only(self):
        """Hash-secured entries are never auto-resequenced; the post still succeeds."""
        self.journal.restrict_mode_hash_table = True

        move1 = self._create_move('2024-08-20')
        move1.action_post()
        self.assertTrue(move1.inalterable_hash)

        move2 = self._create_move('2024-08-10')
        move2.action_post()  # must not raise

        move1.invalidate_recordset(['name'])
        # Names untouched: move1 keeps its hashed name, move2 keeps whatever it was assigned.
        self.assertEqual(move1.name, 'BDR/2024/08/0001')
        self.assertEqual(move2.name, 'BDR/2024/08/0002')

        warning_msg = move2.message_ids.filtered(lambda m: 'secured by a posting hash' in (m.body or ''))
        self.assertTrue(warning_msg, "Expected a warning chatter message explaining the hash-lock skip.")

    def test_posting_via_backdated_menu_resequences_without_journal_toggle(self):
        """Accounting > Backdated Journal Entries sets a context key: entries
        posted through it are resequenced even if the journal toggle is off."""
        self.journal.auto_resequence_backdated = False
        move1 = self._create_move('2024-08-20')
        move1.action_post()

        move2 = self._create_move('2024-08-10')
        move2.with_context(backdated_resequence=True).action_post()

        move1.invalidate_recordset(['name'])
        move2.invalidate_recordset(['name'])
        self.assertEqual(move2.name, 'BDR/2024/08/0001')
        self.assertEqual(move1.name, 'BDR/2024/08/0002')
        self.assertTrue(
            move1.message_ids.filtered(lambda m: 'Automatically resequenced' in (m.body or '')),
            "Expected the audit chatter message on the renamed entry.",
        )

    def test_backdated_menu_and_action_exist(self):
        """The Accounting menu entry opens journal entries with the trigger context."""
        menu = self.env.ref('account_backdated_resequence.menu_backdated_journal_entries')
        action = self.env.ref('account_backdated_resequence.action_backdated_journal_entries')
        self.assertEqual(menu.name, 'Backdated Journal Entries')
        self.assertEqual(menu.parent_id, self.env.ref('account.menu_finance_entries'))
        self.assertEqual(menu.action, action)
        self.assertEqual(action.res_model, 'account.move')
        self.assertIn('backdated_resequence', action.context)

    def test_wrong_prefix_seed_is_corrected_on_next_post_in_that_period(self):
        """Reproduces the actual bug: once one entry's name carries the
        wrong year/month for its own date, core Odoo's *own* sequence
        lookup (not our code) finds that entry by date and copies its wrong
        prefix onto the next entry posted into that same true period -
        which would otherwise hard-block the post entirely with "The Date
        ... isn't aligned with the existing sequence number ...". This
        happens even though the toggle is off and no menu is used - prefix
        correctness is not opt-in.

        The wrong-named reference here is a draft, left unposted:
        core's own lookup domain doesn't filter by state, so it's still
        picked up as an "existing name" for a later post landing in the
        same date range - the same mechanism a posted-but-wrong historical
        entry would cause, without needing hash-chain bookkeeping in the
        test setup.
        """
        self.journal.auto_resequence_backdated = False

        sept_move = self._create_move('2024-09-05')
        sept_move.action_post()
        self.assertEqual(sept_move.name, 'BDR/2024/09/0001')

        bad_ref = self._create_move('2024-08-12')
        bad_ref.name = 'BDR/2024/09/0099'  # draft: no constraint fires on this write

        # A brand-new August entry: core will find the wrong reference (its
        # date is genuinely in August) and copy its "09" prefix, unless our
        # fix catches it - and would otherwise hard-block the post outright.
        new_august_move = self._create_move('2024-08-20')
        new_august_move.action_post()  # must not raise

        new_august_move.invalidate_recordset(['name'])
        self.assertEqual(
            new_august_move.name, 'BDR/2024/08/0001',
            "A new August entry must not inherit a wrong 09 prefix copied from an earlier bad reference.",
        )
        correction_msg = new_august_move.message_ids.filtered(lambda m: 'Corrected sequence' in (m.body or ''))
        self.assertTrue(correction_msg, "Expected an audit chatter message documenting the correction.")

    def test_wrong_prefix_on_hash_locked_journal_warns_only(self):
        """In a hash-secured journal, a newly posted entry is hashed
        immediately inside the same post - so even the entry that just
        inherited a wrong prefix can no longer be renamed; warn instead.

        The wrong reference points at an otherwise-empty month (December),
        not one with its own already-posted chain (like September in the
        other test): reusing a populated chain here would trip core's own,
        unrelated hash-chain gap-detection safety check first, masking the
        thing this test actually verifies.
        """
        self.journal.restrict_mode_hash_table = True

        bad_ref = self._create_move('2024-08-12')
        bad_ref.name = 'BDR/2024/12/0001'  # draft: never hashed, never validated

        new_august_move = self._create_move('2024-08-20')
        new_august_move.action_post()  # must not raise

        new_august_move.invalidate_recordset(['name'])
        self.assertTrue(new_august_move.inalterable_hash)
        self.assertEqual(new_august_move.name, 'BDR/2024/12/0002')
        warning_msg = new_august_move.message_ids.filtered(
            lambda m: 'does not match its Accounting Date' in (m.body or '')
        )
        self.assertTrue(warning_msg, "Expected a warning chatter message about the uncorrectable mismatch.")

    def test_repair_wizard_fixes_existing_corrupted_entries(self):
        """The manual repair wizard cleans up history predating the module -
        entries the automatic, per-post correction never touched because
        they weren't the one being posted."""
        sept_move = self._create_move('2024-09-05')
        sept_move.action_post()

        bad_seed = self._create_move('2024-08-12')
        bad_seed.action_post()
        self._corrupt_move_name(bad_seed, 'BDR/2024/09/0099')
        self.assertEqual(bad_seed.name, 'BDR/2024/09/0099')  # corruption seeded, unaffected by any post

        wizard = self.env['account.backdated.resequence.repair.wizard'].create({
            'journal_ids': [(6, 0, [self.journal.id])],
        })
        wizard.action_scan_and_repair()

        bad_seed.invalidate_recordset(['name'])
        self.assertEqual(bad_seed.name, 'BDR/2024/08/0001')
        self.assertIn('BDR/2024/09/0099', wizard.result_summary)
        self.assertIn('BDR/2024/08/0001', wizard.result_summary)

    def test_repair_wizard_reports_nothing_to_fix_on_clean_data(self):
        move = self._create_move('2024-08-05')
        move.action_post()

        wizard = self.env['account.backdated.resequence.repair.wizard'].create({
            'journal_ids': [(6, 0, [self.journal.id])],
        })
        wizard.action_scan_and_repair()
        self.assertIn('nothing to repair', wizard.result_summary)


class TestBackdatedResequenceConcurrency(TransactionCase):
    def setUp(self):
        super().setUp()
        with self.env.registry.cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            journal = env['account.journal'].create({
                'name': 'concurrency_test_bdr',
                'code': 'CTBDR',
                'type': 'general',
                'auto_resequence_backdated': True,
            })
            account_vals = {
                'code': 'CTBDR',
                'name': 'CTBDR',
                'account_type': 'expense',
            }
            if 'create_asset' in env['account.account']._fields:
                # Enterprise `account_asset` adds a required column here; give it
                # explicitly so this test also runs on an Enterprise database.
                account_vals['create_asset'] = 'no'
            account = env['account.account'].create(account_vals)
            moves = env['account.move'].create([
                {
                    'journal_id': journal.id,
                    'date': fields.Date.from_string(date),
                    'line_ids': [(0, 0, {'name': 'name', 'account_id': account.id})],
                }
                for date in ('2016-01-10', '2016-01-20', '2016-01-05', '2016-01-15')
            ])
            moves.name = False
            moves[0].action_post()
            moves[1].action_post()
            self.assertEqual(moves[:2].mapped('name'), ['CTBDR/2016/01/0001', 'CTBDR/2016/01/0002'])
            env.cr.commit()
        self.data = {
            'move_ids': moves.ids,
            'account_id': account.id,
            'journal_id': journal.id,
            'envs': [
                api.Environment(self.env.registry.cursor(), SUPERUSER_ID, {}),
                api.Environment(self.env.registry.cursor(), SUPERUSER_ID, {}),
                api.Environment(self.env.registry.cursor(), SUPERUSER_ID, {}),
            ],
        }
        self.addCleanup(self.cleanUp)

    def cleanUp(self):
        with self.env.registry.cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            moves = env['account.move'].browse(self.data['move_ids'])
            moves.filtered(lambda x: x.state in ('posted', 'cancel')).button_draft()
            moves.posted_before = False
            moves.unlink()
            journal = env['account.journal'].browse(self.data['journal_id'])
            journal.unlink()
            account = env['account.account'].browse(self.data['account_id'])
            account.unlink()
            env.cr.commit()
        for env in self.data['envs']:
            env.cr.close()

    def test_concurrent_backdated_posting_no_duplicate_or_skipped_numbers(self):
        """Two overlapping transactions backdating into the same journal/period
        must not produce duplicate or skipped sequence numbers.

        Our `SELECT ... FOR UPDATE` lock on the candidate journal/prefix (see
        `_auto_resequence_backdated_one`) correctly raises a PostgreSQL
        SerializationFailure ("could not serialize access due to concurrent
        update") when env1's REPEATABLE READ snapshot predates a commit by
        env2 that touched the same rows - a fixed snapshot can't be repaired
        by a savepoint retry inside the same transaction, only by retrying
        the whole transaction. That whole-transaction retry is exactly what
        `odoo.service.model.retrying` provides, and is the same mechanism
        Odoo's own HTTP/RPC dispatch and cron runner wrap every real request
        in - so it's used here too, to exercise the code the way it will
        actually run in production rather than a raw, non-retried call.
        """
        env0, env1, env2 = self.data['envs']

        # Start env1's transaction here to simulate overlap with env2.
        env1.cr.execute('SELECT 1')

        # env2 posts a backdated entry (2016-01-05, before both existing entries) and commits.
        move_env2 = env2['account.move'].browse(self.data['move_ids'][2])
        move_env2.action_post()
        env2.cr.commit()

        # env1 posts another backdated entry (2016-01-15) after env2 committed,
        # wrapped the same way a real request would be.
        move_env1 = env1['account.move'].browse(self.data['move_ids'][3])
        retrying(functools.partial(move_env1.action_post), env1)
        env1.cr.commit()

        moves = env0['account.move'].browse(self.data['move_ids'])
        sequence_numbers = moves.mapped('sequence_number')
        self.assertEqual(sorted(sequence_numbers), [1, 2, 3, 4], "Sequence numbers must be unique with no gaps.")

        # Final chronological order (by date) must match ascending sequence_number.
        ordered_by_date = moves.sorted('date')
        ordered_by_seq = moves.sorted('sequence_number')
        self.assertEqual(ordered_by_date.ids, ordered_by_seq.ids)
