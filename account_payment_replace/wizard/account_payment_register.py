# Copyright 2026 Intrepidux
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import api, models


class AccountPaymentRegister(models.TransientModel):
    _inherit = "account.payment.register"

    @api.depends("payment_type", "journal_id")
    def _compute_payment_method_line_id(self):
        """Keep a valid method when prefilling edit/replace (core always picks [0])."""
        for wizard in self:
            available = wizard.journal_id._get_available_payment_method_lines(
                wizard.payment_type
            )
            if wizard.payment_method_line_id in available:
                wizard.payment_method_line_id = wizard.payment_method_line_id
            elif available:
                wizard.payment_method_line_id = available[0]._origin
            else:
                wizard.payment_method_line_id = False

    def _resolve_payment_method_line(self, preferred_line_id=False):
        self.ensure_one()
        available = self.journal_id._get_available_payment_method_lines(
            self.payment_type
        )
        preferred = self.env["account.payment.method.line"].browse(
            preferred_line_id
        )
        if preferred and preferred in available:
            return preferred
        return available[:1]

    def _create_payments(self):
        edit_payment = (
            self.env["account.payment"]
            .browse(self.env.context.get("edit_payment_id"))
            .exists()
        )
        if edit_payment and edit_payment.state == "draft":
            return edit_payment._apply_edit_from_wizard(self)

        payments = super()._create_payments()
        replaced = (
            self.env["account.payment"]
            .browse(self.env.context.get("replaced_payment_id"))
            .exists()
        )
        if replaced and payments:
            payments._link_from_replaced_payment(replaced)
        return payments
