# Copyright 2026 Intrepidux
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import _, fields, models
from odoo.exceptions import UserError


class AccountMove(models.Model):
    _inherit = "account.move"

    account_payment_modify_mode = fields.Selection(
        related="company_id.account_payment_modify_mode",
    )

    def _get_replaceable_payments(self):
        """Posted, replaceable payments reconciled with this invoice/bill."""
        self.ensure_one()
        return self._get_reconciled_payments().filtered(
            lambda pay: pay.state == "posted"
            and not pay.replacement_payment_id
            and not pay._is_bank_statement_reconciled()
            and not pay.is_internal_transfer
            and pay.move_id.show_reset_to_draft_button
        )

    def action_replace_payment(self):
        """Entry point from invoice/bill: replace its reconciled payment(s)."""
        self.ensure_one()
        if self.state != "posted" or not self.is_invoice(include_receipts=True):
            raise UserError(
                _("Replace Payment is only available on posted invoices or bills.")
            )
        if self.payment_state not in ("paid", "partial", "in_payment"):
            raise UserError(
                _("This document has no payment to replace.")
            )
        payments = self._get_replaceable_payments()
        if not payments:
            raise UserError(
                _(
                    "No replaceable payment found. "
                    "Payments matched to a bank statement, already replaced, "
                    "or without invoice reconciliation cannot be replaced."
                )
            )
        if len(payments) == 1:
            return payments.action_replace_payment()
        # Several payments: open them so the user picks which one to replace
        return {
            "name": _("Replace Payment"),
            "type": "ir.actions.act_window",
            "res_model": "account.payment",
            "view_mode": "tree,form",
            "views": [[False, "tree"], [False, "form"]],
            "domain": [("id", "in", payments.ids)],
            "context": {"create": False},
            "target": "current",
        }
