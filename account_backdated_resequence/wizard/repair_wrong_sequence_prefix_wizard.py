# -*- coding: utf-8 -*-
from odoo import _, fields, models


class RepairWrongSequencePrefixWizard(models.TransientModel):
    _name = 'account.backdated.resequence.repair.wizard'
    _description = "Repair journal entries whose sequence prefix doesn't match their date"

    journal_ids = fields.Many2many(
        'account.journal', string="Journals",
        domain="[('type', 'in', ['sale', 'purchase', 'general'])]",
        help="Leave empty to scan every journal.",
    )
    result_summary = fields.Text(readonly=True)

    def action_scan_and_repair(self):
        """One-off, on-demand repair for entries already corrupted by the
        core Odoo bug described in
        account.move._correct_wrong_sequence_prefix_one - a name whose
        year/month was copied from an earlier, already-wrong entry rather
        than from its own date. Going forward, _post() catches this
        automatically on every new posting; this wizard is for cleaning up
        history that predates the module, or entries posted while the
        server was down.
        """
        self.ensure_one()
        domain = [('state', '=', 'posted'), ('name', 'not in', ('/', False, ''))]
        if self.journal_ids:
            domain.append(('journal_id', 'in', self.journal_ids.ids))
        moves = self.env['account.move'].search(domain)
        candidates = moves.filtered(lambda m: m._deduce_sequence_number_reset(m.name) != 'never')

        before = {m.id: m.name for m in candidates}
        candidates._correct_wrong_sequence_prefix()
        candidates.invalidate_recordset(['name'])
        fixed = [(before[m.id], m.name) for m in candidates if m.name != before[m.id]]

        if fixed:
            lines = "\n".join(f"  {old}  ->  {new}" for old, new in fixed)
            self.result_summary = _("%s entries corrected:\n%s") % (len(fixed), lines)
        else:
            self.result_summary = _(
                "No mismatched entries found among %s posted entries scanned - nothing to repair."
            ) % len(candidates)

        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
