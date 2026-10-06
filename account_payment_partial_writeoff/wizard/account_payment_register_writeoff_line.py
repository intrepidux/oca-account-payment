# Copyright 2026 Glowicom
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import api, fields, models


class AccountPaymentRegisterWriteoffLine(models.TransientModel):
    _name = "account.payment.register.writeoff.line"
    _description = "Invoice lines on register payment wizard (partial write-off)"

    wizard_id = fields.Many2one(
        comodel_name="account.payment.register",
        string="Wizard",
        required=True,
        ondelete="cascade",
    )
    invoice_id = fields.Many2one(
        comodel_name="account.move",
        string="Invoice",
        required=True,
    )
    currency_id = fields.Many2one(related="invoice_id.currency_id")

    date_invoice = fields.Date(related="invoice_id.invoice_date")
    date_due = fields.Date(related="invoice_id.invoice_date_due")
    amount_total = fields.Monetary(
        related="invoice_id.amount_total",
        currency_field="currency_id",
    )
    residual = fields.Monetary(
        related="invoice_id.amount_residual",
        currency_field="currency_id",
    )

    add_invoice = fields.Boolean(string="Select", default=True)
    allocated_amount = fields.Monetary(
        string="Cash amount",
        currency_field="currency_id",
        default=0.0,
    )
    amount_to_reconcile = fields.Monetary(
        string="To reconcile",
        compute="_compute_amount_to_reconcile",
        currency_field="currency_id",
    )

    @api.depends(
        "add_invoice",
        "allocated_amount",
        "wizard_id.writeoff_amount",
        "wizard_id.post_difference_on_open",
        "wizard_id.payment_difference_handling",
        "wizard_id.register_writeoff_line_ids.add_invoice",
    )
    def _compute_amount_to_reconcile(self):
        for line in self:
            if not line.add_invoice:
                line.amount_to_reconcile = 0.0
                continue
            total = line.allocated_amount
            wizard = line.wizard_id
            if (
                wizard.payment_difference_handling == "open"
                and wizard.post_difference_on_open
                and not wizard.currency_id.is_zero(wizard.writeoff_amount)
            ):
                selected = wizard.register_writeoff_line_ids.filtered("add_invoice")
                if line in selected and len(selected) == 1:
                    total += wizard.writeoff_amount
            line.amount_to_reconcile = total

    @api.onchange("add_invoice", "allocated_amount")
    def _onchange_add_invoice(self):
        for line in self:
            if not line.add_invoice or not line.currency_id.is_zero(line.allocated_amount):
                continue
            wizard = line.wizard_id
            if (
                wizard
                and wizard.payment_difference_handling == "open"
                and not wizard.currency_id.is_zero(wizard.amount)
            ):
                line.allocated_amount = min(line.residual, wizard.amount)
            elif line.add_invoice:
                line.allocated_amount = line.residual
