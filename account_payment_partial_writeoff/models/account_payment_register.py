# Copyright 2026 Glowicom
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class AccountPaymentRegister(models.TransientModel):
    _inherit = "account.payment.register"

    post_difference_on_open = fields.Boolean(
        string="Contabilizar diferencia",
        default=False,
    )
    open_writeoff_account_id = fields.Many2one(
        comodel_name="account.account",
        string="Difference Account",
        domain="[('deprecated', '=', False), ('company_id', '=', company_id)]",
    )
    open_writeoff_label = fields.Char(
        string="Journal Item Label",
        default="Write-Off",
    )
    writeoff_amount = fields.Monetary(
        string="Write-Off Amount",
        currency_field="currency_id",
    )
    option_select_writeoff_invoices = fields.Boolean(string="Select all invoices")
    register_writeoff_line_ids = fields.One2many(
        comodel_name="account.payment.register.writeoff.line",
        inverse_name="wizard_id",
        string="Invoice detail",
    )
    show_writeoff_invoice_detail = fields.Boolean(
        compute="_compute_show_writeoff_invoice_detail",
    )

    @api.depends(
        "can_edit_wizard",
        "payment_type",
        "partner_type",
        "payment_difference_handling",
        "post_difference_on_open",
    )
    def _compute_show_writeoff_invoice_detail(self):
        for wizard in self:
            wizard.show_writeoff_invoice_detail = bool(
                wizard.can_edit_wizard
                and wizard.payment_type in ("inbound", "outbound")
                and wizard.partner_type in ("customer", "supplier")
                and wizard.payment_difference_handling == "open"
                and wizard.post_difference_on_open
            )

    def _should_post_partial_writeoff(self):
        self.ensure_one()
        account = self.writeoff_account_id or self.open_writeoff_account_id
        return (
            self.payment_difference_handling == "open"
            and self.post_difference_on_open
            and account
            and not self.currency_id.is_zero(self.writeoff_amount)
        )

    def _validate_writeoff_fields(self):
        for wizard in self:
            if wizard.payment_difference_handling == "reconcile":
                if not wizard.writeoff_account_id:
                    raise UserError(
                        _("Select the account to post the payment difference.")
                    )
                if not wizard.writeoff_label:
                    raise UserError(_("Set a label for the write-off."))
            elif wizard._should_post_partial_writeoff() or (
                wizard.payment_difference_handling == "open"
                and wizard.post_difference_on_open
            ):
                if not (wizard.open_writeoff_account_id or wizard.writeoff_account_id):
                    raise UserError(
                        _("Select the account to post the partial difference.")
                    )
                if wizard.currency_id.is_zero(wizard.writeoff_amount):
                    raise UserError(_("Set a write-off amount greater than zero."))
                if not (wizard.open_writeoff_label or wizard.writeoff_label):
                    raise UserError(_("Set a label for the write-off."))

    def _get_source_amount_for_compare(self):
        self.ensure_one()
        if self.source_currency_id == self.currency_id:
            return self.source_amount_currency
        if self.currency_id == self.company_id.currency_id:
            return self.source_amount
        return self.company_id.currency_id._convert(
            self.source_amount,
            self.currency_id,
            self.company_id,
            self.payment_date or fields.Date.today(),
        )

    def _get_wizard_cash_for_lines(self):
        """Cash from Importe when user entered a partial payment."""
        self.ensure_one()
        if not self.can_edit_wizard or self.currency_id.is_zero(self.amount):
            return None
        source = self._get_source_amount_for_compare()
        if self.currency_id.compare_amounts(self.amount, source) < 0:
            return self.amount
        return None

    def _load_register_writeoff_invoices(self):
        for wizard in self:
            if (
                not wizard.post_difference_on_open
                or wizard.payment_difference_handling != "open"
                or not wizard.line_ids
            ):
                continue
            invoices = wizard.line_ids.move_id
            existing = {
                line.invoice_id.id: line for line in wizard.register_writeoff_line_ids
            }
            cash = wizard._get_wizard_cash_for_lines()
            commands = []
            for invoice in invoices:
                if invoice.id not in existing:
                    vals = {"invoice_id": invoice.id, "add_invoice": True}
                    if cash is not None and len(invoices) == 1:
                        vals["allocated_amount"] = min(invoice.amount_residual, cash)
                    commands.append((0, 0, vals))
            stale = wizard.register_writeoff_line_ids.filtered(
                lambda line: line.invoice_id.id not in invoices.ids
            )
            if stale:
                commands.extend((2, line.id) for line in stale)
            if commands:
                wizard.register_writeoff_line_ids = commands
            wizard._sync_writeoff_lines_cash_from_amount()

    @api.onchange("line_ids")
    def _onchange_line_ids_writeoff_invoices(self):
        self._load_register_writeoff_invoices()

    @api.onchange("option_select_writeoff_invoices")
    def _onchange_option_select_writeoff_invoices(self):
        for wizard in self:
            for line in wizard.register_writeoff_line_ids:
                line.add_invoice = wizard.option_select_writeoff_invoices

    def _sync_writeoff_lines_cash_from_amount(self):
        """Keep invoice cash lines aligned with wizard Importe (single invoice)."""
        for wizard in self.filtered(
            lambda w: w.post_difference_on_open and w.register_writeoff_line_ids
        ):
            selected = wizard.register_writeoff_line_ids.filtered("add_invoice")
            if len(selected) != 1 or wizard.currency_id.is_zero(wizard.amount):
                continue
            line = selected[0]
            cash = min(line.residual, wizard.amount)
            if line.currency_id.compare_amounts(line.allocated_amount, cash) != 0:
                line.allocated_amount = cash

    @api.onchange("amount")
    def _onchange_amount_sync_writeoff_lines(self):
        self._sync_writeoff_lines_cash_from_amount()

    @api.depends(
        "amount",
        "writeoff_amount",
        "post_difference_on_open",
        "payment_difference_handling",
        "source_amount",
        "source_amount_currency",
        "source_currency_id",
        "currency_id",
        "company_id",
        "payment_date",
    )
    def _compute_payment_difference(self):
        super()._compute_payment_difference()
        for wizard in self:
            if (
                wizard.payment_difference_handling == "open"
                and wizard.post_difference_on_open
                and not wizard.currency_id.is_zero(wizard.writeoff_amount)
            ):
                wizard.payment_difference = wizard.currency_id.round(
                    wizard.payment_difference - wizard.writeoff_amount
                )
                if wizard.currency_id.compare_amounts(wizard.payment_difference, 0.0) < 0:
                    wizard.payment_difference = 0.0

    def _sync_open_writeoff_to_main_fields(self):
        for wizard in self:
            if (
                wizard.payment_difference_handling == "open"
                and wizard.post_difference_on_open
            ):
                wizard.writeoff_account_id = wizard.open_writeoff_account_id
                wizard.writeoff_label = wizard.open_writeoff_label or "Write-Off"
            elif wizard.payment_difference_handling == "open":
                wizard.writeoff_account_id = False
                wizard.writeoff_label = "Write-Off"

    @api.onchange(
        "open_writeoff_account_id",
        "open_writeoff_label",
        "writeoff_amount",
        "post_difference_on_open",
    )
    def _onchange_open_writeoff_fields(self):
        self._sync_open_writeoff_to_main_fields()

    @api.onchange("payment_difference_handling")
    def _onchange_payment_difference_handling(self):
        for wizard in self:
            if wizard.payment_difference_handling == "reconcile":
                wizard.post_difference_on_open = False
                wizard.writeoff_amount = 0.0
                wizard.open_writeoff_account_id = False
                wizard.open_writeoff_label = "Write-Off"
            elif wizard.payment_difference_handling == "open":
                wizard.writeoff_account_id = False
                wizard.writeoff_label = "Write-Off"
            self._sync_open_writeoff_to_main_fields()

    @api.onchange("post_difference_on_open")
    def _onchange_post_difference_on_open(self):
        for wizard in self:
            if not wizard.post_difference_on_open:
                wizard.writeoff_amount = 0.0
                wizard.open_writeoff_account_id = False
                wizard.open_writeoff_label = "Write-Off"
            else:
                if wizard.open_writeoff_account_id:
                    wizard.writeoff_account_id = wizard.open_writeoff_account_id
                    wizard.writeoff_label = wizard.open_writeoff_label or "Write-Off"
                wizard._load_register_writeoff_invoices()
            self._sync_open_writeoff_to_main_fields()

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        line_ids = []
        if res.get("line_ids"):
            line_ids = res["line_ids"][0][2]
        if not line_ids and self._context.get("active_model") == "account.move":
            active_ids = self._context.get("active_ids") or []
            if active_ids:
                line_ids = (
                    self.env["account.move"]
                    .browse(active_ids)
                    .line_ids.filtered(
                        lambda line: line.account_internal_type
                        in ("receivable", "payable")
                        and (
                            (
                                line.currency_id
                                and not line.currency_id.is_zero(
                                    line.amount_residual_currency
                                )
                            )
                            or (
                                line.company_currency_id
                                and not line.company_currency_id.is_zero(
                                    line.amount_residual
                                )
                            )
                        )
                    )
                    .ids
                )
        if line_ids and "register_writeoff_line_ids" in fields_list:
            invoices = self.env["account.move.line"].browse(line_ids).move_id
            res["register_writeoff_line_ids"] = [
                (0, 0, {"invoice_id": inv.id, "add_invoice": True})
                for inv in invoices
            ]
        return res

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._load_register_writeoff_invoices()
        return records

    def _get_payment_writeoff_line_commands(self):
        self.ensure_one()
        selected = self.register_writeoff_line_ids.filtered("add_invoice")
        commands = []
        total_allocated = sum(selected.mapped("allocated_amount"))
        fallback_cash = (
            self.amount if self.currency_id.is_zero(total_allocated) else None
        )
        for idx, wline in enumerate(selected):
            allocated = wline.allocated_amount
            if fallback_cash is not None:
                allocated = fallback_cash if idx == 0 else 0.0
            commands.append(
                (
                    0,
                    0,
                    {
                        "invoice_id": wline.invoice_id.id,
                        "add_invoice": True,
                        "allocated_amount": allocated,
                    },
                )
            )
        return commands

    def action_create_payments(self):
        self._validate_writeoff_fields()
        self._sync_open_writeoff_to_main_fields()
        return super().action_create_payments()

    def _create_payment_vals_from_wizard(self):
        self._sync_open_writeoff_to_main_fields()
        payment_vals = super()._create_payment_vals_from_wizard()
        if (
            self.payment_difference_handling == "open"
            and self.post_difference_on_open
        ):
            account = self.open_writeoff_account_id or self.writeoff_account_id
            if account and not self.currency_id.is_zero(self.writeoff_amount):
                payment_vals["write_off_line_vals"] = {
                    "name": self.writeoff_label
                    or self.open_writeoff_label
                    or _("Write-Off"),
                    "amount": self.writeoff_amount,
                    "account_id": account.id,
                }
                payment_vals["amount"] = self.amount
        payment_vals.update(
            {
                "post_difference_on_open": self.post_difference_on_open,
                "writeoff_amount": self.writeoff_amount,
                "payment_difference_handling": self.payment_difference_handling,
                "writeoff_account_id": (
                    self.open_writeoff_account_id.id
                    or self.writeoff_account_id.id
                    or False
                ),
                "writeoff_label": self.writeoff_label
                or self.open_writeoff_label
                or "Write-Off",
            }
        )
        if self.register_writeoff_line_ids:
            commands = []
            if self.env.context.get("edit_payment_id"):
                commands.append((5, 0, 0))
            commands.extend(self._get_payment_writeoff_line_commands())
            payment_vals["payment_writeoff_line_ids"] = commands
        return payment_vals
