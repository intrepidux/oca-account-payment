# Copyright 2026 Glowicom
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare


class AccountPayment(models.Model):
    _inherit = "account.payment"

    payment_difference_handling = fields.Selection(
        [
            ("open", "Keep open"),
            ("reconcile", "Mark as fully paid"),
        ],
        string="Payment Difference Handling",
        default="open",
        copy=False,
    )
    post_difference_on_open = fields.Boolean(
        string="Contabilizar diferencia",
        default=False,
        copy=False,
        help="When keeping the invoice open, post the write-off amount to the "
        "selected account so the residual reflects only the real pending balance.",
    )
    writeoff_account_id = fields.Many2one(
        comodel_name="account.account",
        string="Difference Account",
        copy=False,
        domain="[('deprecated', '=', False), ('company_id', '=', company_id)]",
    )
    writeoff_label = fields.Char(string="Journal Item Label", default="Write-Off")
    writeoff_amount = fields.Monetary(
        string="Write-Off",
        currency_field="currency_id",
        copy=False,
    )
    source_amount = fields.Monetary(
        string="Amount Due",
        compute="_compute_writeoff_amounts",
        currency_field="currency_id",
    )
    payment_difference = fields.Monetary(
        string="Payment Difference",
        compute="_compute_writeoff_amounts",
        currency_field="currency_id",
    )
    option_select_writeoff_invoices = fields.Boolean(string="Select all invoices")

    payment_writeoff_line_ids = fields.One2many(
        comodel_name="account.payment.writeoff.line",
        inverse_name="payment_id",
        string="Invoice detail",
    )

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _should_post_partial_writeoff(self):
        self.ensure_one()
        return (
            self.payment_difference_handling == "open"
            and self.post_difference_on_open
            and self.writeoff_account_id
            and not self.currency_id.is_zero(self.writeoff_amount)
        )

    def _get_write_off_line_vals(self):
        self.ensure_one()
        if not self._should_post_partial_writeoff():
            return {}
        return {
            "name": self.writeoff_label or _("Write-Off"),
            "amount": self.writeoff_amount,
            "account_id": self.writeoff_account_id.id,
        }

    def _rebuild_move_with_partial_writeoff(self):
        """Ensure draft move lines include cash + write-off + counterpart."""
        from odoo import Command

        for payment in self.filtered(
            lambda p: p.move_id and p._should_post_partial_writeoff()
        ):
            write_off_line_vals = payment._get_write_off_line_vals()
            line_vals_list = payment._prepare_move_line_default_vals(
                write_off_line_vals=write_off_line_vals
            )
            liquidity_lines, counterpart_lines, writeoff_lines = (
                payment._seek_for_lines()
            )
            line_ids_commands = [
                Command.update(liquidity_lines.id, line_vals_list[0])
                if liquidity_lines
                else Command.create(line_vals_list[0]),
                Command.update(counterpart_lines.id, line_vals_list[1])
                if counterpart_lines
                else Command.create(line_vals_list[1]),
            ]
            for line in writeoff_lines:
                line_ids_commands.append(Command.delete(line.id))
            for extra_line_vals in line_vals_list[2:]:
                line_ids_commands.append(Command.create(extra_line_vals))
            payment.move_id.write({"line_ids": line_ids_commands})

    def _get_invoice_type_for_payment(self):
        mapping = {
            ("inbound", "customer"): "out_invoice",
            ("outbound", "customer"): "out_refund",
            ("outbound", "supplier"): "in_invoice",
            ("inbound", "supplier"): "in_refund",
        }
        return mapping.get((self.payment_type, self.partner_type))

    def _get_selected_writeoff_lines(self):
        self.ensure_one()
        return self.payment_writeoff_line_ids.filtered("add_invoice")

    # -------------------------------------------------------------------------
    # Computes
    # -------------------------------------------------------------------------

    @api.depends(
        "payment_writeoff_line_ids.add_invoice",
        "payment_writeoff_line_ids.residual",
        "payment_writeoff_line_ids.allocated_amount",
        "writeoff_amount",
        "amount",
        "post_difference_on_open",
        "payment_difference_handling",
    )
    def _compute_writeoff_amounts(self):
        for payment in self:
            selected = payment._get_selected_writeoff_lines()
            payment.source_amount = sum(selected.mapped("residual"))
            applied = sum(selected.mapped("allocated_amount"))
            if payment._should_post_partial_writeoff():
                applied += payment.writeoff_amount
            payment.payment_difference = payment.source_amount - applied

    # -------------------------------------------------------------------------
    # Onchanges
    # -------------------------------------------------------------------------

    @api.onchange("payment_type", "partner_type", "partner_id", "currency_id")
    def _onchange_load_open_writeoff_invoices(self):
        if (
            not self.payment_type
            or not self.partner_type
            or not self.partner_id
            or not self.currency_id
            or self.is_internal_transfer
        ):
            return

        invoice_type = self._get_invoice_type_for_payment()
        if not invoice_type:
            self.payment_writeoff_line_ids = [(5, 0, 0)]
            return

        invoices = self.env["account.move"].search(
            [
                ("partner_id", "child_of", self.partner_id.id),
                ("state", "=", "posted"),
                ("move_type", "=", invoice_type),
                ("payment_state", "in", ("not_paid", "partial")),
                ("currency_id", "=", self.currency_id.id),
                ("amount_residual", "!=", 0.0),
            ]
        )
        existing = {line.invoice_id.id: line for line in self.payment_writeoff_line_ids}
        commands = []
        for invoice in invoices:
            if invoice.id not in existing:
                commands.append((0, 0, {"invoice_id": invoice.id}))
        stale = self.payment_writeoff_line_ids.filtered(
            lambda line: line.invoice_id.id not in invoices.ids
        )
        if stale:
            commands.extend((2, line.id) for line in stale)
        if commands:
            self.payment_writeoff_line_ids = commands

    @api.onchange("option_select_writeoff_invoices")
    def _onchange_option_select_writeoff_invoices(self):
        for payment in self:
            for line in payment.payment_writeoff_line_ids:
                line.add_invoice = payment.option_select_writeoff_invoices
            payment._sync_amount_from_writeoff_lines()

    @api.onchange(
        "payment_writeoff_line_ids",
        "post_difference_on_open",
        "writeoff_amount",
        "payment_difference_handling",
    )
    def _onchange_payment_writeoff_lines(self):
        for payment in self:
            payment._sync_amount_from_writeoff_lines()

    @api.onchange("payment_difference_handling")
    def _onchange_payment_difference_handling(self):
        for payment in self:
            if payment.payment_difference_handling != "open":
                payment.post_difference_on_open = False
                payment.writeoff_amount = 0.0

    @api.onchange("post_difference_on_open")
    def _onchange_post_difference_on_open(self):
        for payment in self:
            if not payment.post_difference_on_open:
                payment.writeoff_amount = 0.0
                payment.writeoff_account_id = False

    # -------------------------------------------------------------------------
    # Sync / persistence
    # -------------------------------------------------------------------------

    def _sync_amount_from_writeoff_lines(self, persist=False):
        """Sync cash amount from selected write-off lines.

        Never overwrite a positive payment amount with 0 when lines have no
        allocated cash yet (common when creating from the register wizard).
        """
        for payment in self.filtered(
            lambda p: p.state == "draft" and p._should_post_partial_writeoff()
        ):
            selected = payment._get_selected_writeoff_lines()
            if not selected:
                continue
            amount = sum(selected.mapped("allocated_amount"))
            if payment.currency_id.is_zero(amount):
                continue
            if payment.currency_id.compare_amounts(payment.amount, amount) == 0:
                continue
            if persist and payment.id:
                payment.with_context(
                    skip_payment_writeoff_sync=True,
                    skip_account_move_synchronization=True,
                ).write({"amount": amount})
            else:
                payment.amount = amount

    def _ensure_writeoff_line_allocation(self):
        """If lines are selected but cash is 0, put payment.amount on them."""
        for payment in self.filtered(
            lambda p: p.state == "draft" and p._should_post_partial_writeoff()
        ):
            selected = payment._get_selected_writeoff_lines()
            if not selected:
                continue
            allocated = sum(selected.mapped("allocated_amount"))
            if not payment.currency_id.is_zero(allocated):
                continue
            if payment.currency_id.is_zero(payment.amount):
                continue
            # Single invoice: all cash there. Multi: put all on first selected.
            first = selected[0]
            first.with_context(skip_payment_writeoff_sync=True).write(
                {"allocated_amount": payment.amount}
            )

    @api.model_create_multi
    def create(self, vals_list):
        payments = super().create(vals_list)
        payments._ensure_writeoff_line_allocation()
        payments._sync_amount_from_writeoff_lines(persist=True)
        payments.filtered(lambda p: p.state == "draft")._rebuild_move_with_partial_writeoff()
        return payments

    def write(self, vals):
        res = super().write(vals)
        if not self.env.context.get("skip_payment_writeoff_sync"):
            trigger_fields = {
                "payment_writeoff_line_ids",
                "post_difference_on_open",
                "writeoff_amount",
                "payment_difference_handling",
                "option_select_writeoff_invoices",
            }
            if trigger_fields.intersection(vals.keys()):
                self._ensure_writeoff_line_allocation()
                self._sync_amount_from_writeoff_lines(persist=True)
        return res

    # -------------------------------------------------------------------------
    # Move lines / sync
    # -------------------------------------------------------------------------

    def _prepare_move_line_default_vals(self, write_off_line_vals=None):
        self.ensure_one()
        if self._should_post_partial_writeoff():
            write_off_line_vals = self._get_write_off_line_vals()
        elif (
            not write_off_line_vals
            and self.payment_difference_handling == "reconcile"
            and self.writeoff_account_id
            and not self.currency_id.is_zero(self.payment_difference)
        ):
            write_off_line_vals = {
                "name": self.writeoff_label or _("Write-Off"),
                "amount": self.payment_difference,
                "account_id": self.writeoff_account_id.id,
            }
        return super()._prepare_move_line_default_vals(
            write_off_line_vals=write_off_line_vals
        )

    def _synchronize_to_moves(self, changed_fields):
        if self._context.get("skip_account_move_synchronization"):
            return super()._synchronize_to_moves(changed_fields)

        writeoff_fields = {
            "post_difference_on_open",
            "writeoff_account_id",
            "writeoff_label",
            "writeoff_amount",
            "payment_difference_handling",
        }
        if writeoff_fields.intersection(changed_fields):
            changed_fields = list(set(changed_fields) | writeoff_fields | {"amount"})

        res = super()._synchronize_to_moves(changed_fields)
        self.filtered(lambda p: p.state == "draft")._rebuild_move_with_partial_writeoff()
        return res

    # -------------------------------------------------------------------------
    # Post / reconcile
    # -------------------------------------------------------------------------

    def _validate_partial_writeoff(self):
        for payment in self.filtered(
            lambda p: p._should_post_partial_writeoff() and p.payment_writeoff_line_ids
        ):
            if not payment.writeoff_account_id:
                raise UserError(_("Select a write-off account."))
            selected = payment._get_selected_writeoff_lines()
            if not selected:
                raise UserError(_("Select at least one invoice."))
            allocated = sum(selected.mapped("allocated_amount"))
            applied = allocated + payment.writeoff_amount
            if (
                float_compare(
                    payment.amount,
                    allocated,
                    precision_rounding=payment.currency_id.rounding,
                )
                != 0
            ):
                raise UserError(
                    _(
                        "Payment amount (%(pay)s) must equal the sum of cash "
                        "amounts (%(cash)s)."
                    )
                    % {"pay": payment.amount, "cash": allocated}
                )
            if (
                float_compare(
                    applied,
                    payment.source_amount,
                    precision_rounding=payment.currency_id.rounding,
                )
                > 0
            ):
                raise UserError(
                    _(
                        "Applied amount (%(applied)s) exceeds the selected "
                        "residual (%(residual)s)."
                    )
                    % {"applied": applied, "residual": payment.source_amount}
                )

    def action_post(self):
        self._validate_partial_writeoff()
        self.filtered(lambda p: p.state == "draft")._rebuild_move_with_partial_writeoff()
        res = super().action_post()
        for payment in self.filtered(
            lambda p: p.payment_writeoff_line_ids and not p.is_internal_transfer
        ):
            payment._reconcile_writeoff_invoices()
        return res

    def _reconcile_writeoff_invoices(self):
        self.ensure_one()
        selected = self.payment_writeoff_line_ids.filtered(
            lambda line: line.amount_to_reconcile
        )
        if not selected:
            return

        account = self.destination_account_id
        pay_lines = self.move_id.line_ids.filtered(
            lambda line: line.account_id == account and not line.reconciled
        )
        inv_lines = self.env["account.move.line"]
        for line in selected:
            inv_lines |= line.invoice_id.line_ids.filtered(
                lambda aml: aml.account_id == account and not aml.reconciled
            )
        if pay_lines and inv_lines:
            (pay_lines + inv_lines).reconcile()

    def _prepare_replace_payment_vals(self):
        """Prefill edit/replace wizard with partial write-off fields."""
        vals = super()._prepare_replace_payment_vals()
        self.ensure_one()
        if self._should_post_partial_writeoff():
            vals["partial_writeoff_vals"] = {
                "writeoff_account_id": self.writeoff_account_id.id,
                "writeoff_label": self.writeoff_label or _("Write-Off"),
                "writeoff_amount": self.writeoff_amount,
            }
            selected = self._get_selected_writeoff_lines()
            if selected:
                vals["register_writeoff_line_ids"] = [
                    (
                        0,
                        0,
                        {
                            "invoice_id": line.invoice_id.id,
                            "add_invoice": True,
                            "allocated_amount": line.allocated_amount,
                        },
                    )
                    for line in selected
                ]
        return vals
