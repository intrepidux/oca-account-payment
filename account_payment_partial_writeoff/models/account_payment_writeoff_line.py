# Copyright 2026 Glowicom
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import api, fields, models


class AccountPaymentWriteoffLine(models.Model):
    _name = "account.payment.writeoff.line"
    _description = "Invoice lines on payment (partial write-off)"

    payment_id = fields.Many2one(
        comodel_name="account.payment",
        string="Payment",
        required=True,
        ondelete="cascade",
    )
    invoice_id = fields.Many2one(
        comodel_name="account.move",
        string="Invoice",
        required=True,
    )
    currency_id = fields.Many2one(related="invoice_id.currency_id")
    payment_state = fields.Selection(related="payment_id.state", store=True)

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

    add_invoice = fields.Boolean(string="Select", default=False)
    allocated_amount = fields.Monetary(
        string="Cash amount",
        currency_field="currency_id",
        default=0.0,
    )
    amount_to_reconcile = fields.Monetary(
        string="To reconcile",
        compute="_compute_amount_to_reconcile",
        store=True,
        currency_field="currency_id",
    )

    @api.depends(
        "add_invoice",
        "allocated_amount",
        "payment_id.writeoff_amount",
        "payment_id.post_difference_on_open",
        "payment_id.payment_difference_handling",
        "payment_id.payment_writeoff_line_ids.add_invoice",
    )
    def _compute_amount_to_reconcile(self):
        for line in self:
            if not line.add_invoice:
                line.amount_to_reconcile = 0.0
                continue
            total = line.allocated_amount
            payment = line.payment_id
            if payment._should_post_partial_writeoff():
                selected = payment._get_selected_writeoff_lines()
                if line in selected and len(selected) == 1:
                    total += payment.writeoff_amount
            line.amount_to_reconcile = total

    @api.onchange("add_invoice")
    def _onchange_add_invoice(self):
        for line in self:
            if line.add_invoice and line.currency_id.is_zero(line.allocated_amount):
                line.allocated_amount = line.residual

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        lines.mapped("payment_id")._sync_amount_from_writeoff_lines(persist=True)
        return lines

    def write(self, vals):
        res = super().write(vals)
        if not self.env.context.get("skip_payment_writeoff_sync"):
            self.mapped("payment_id")._sync_amount_from_writeoff_lines(persist=True)
        return res
