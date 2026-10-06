# Copyright 2026 Intrepidux
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class AccountPayment(models.Model):
    _inherit = "account.payment"

    account_payment_modify_mode = fields.Selection(
        related="company_id.account_payment_modify_mode",
    )
    replaced_payment_id = fields.Many2one(
        comodel_name="account.payment",
        string="Replaced Payment",
        readonly=True,
        copy=False,
        index=True,
        help="Original payment that this payment replaces.",
    )
    replacement_payment_id = fields.Many2one(
        comodel_name="account.payment",
        string="Replacement Payment",
        readonly=True,
        copy=False,
        index=True,
        help="New payment that replaced this one.",
    )
    is_replaced = fields.Boolean(
        string="Is Replaced",
        compute="_compute_is_replaced",
        store=True,
    )

    @api.depends("replacement_payment_id")
    def _compute_is_replaced(self):
        for payment in self:
            payment.is_replaced = bool(payment.replacement_payment_id)

    def _check_can_modify(self, mode):
        """Validate that this payment can be corrected via the wizard."""
        self.ensure_one()
        if not self.env.user.has_group(
            "account_payment_replace.group_account_payment_replace"
        ):
            raise UserError(
                _("You do not have permission to modify payments.")
            )
        if self.state != "posted":
            raise UserError(_("Only posted payments can be modified."))
        if mode == "replace" and self.replacement_payment_id:
            raise UserError(
                _("This payment has already been replaced by %s.")
                % self.replacement_payment_id.display_name
            )
        if self.is_internal_transfer:
            raise UserError(
                _("Internal transfers cannot be modified with this action.")
            )
        if self._is_bank_statement_reconciled():
            raise UserError(
                _(
                    "This payment is reconciled with a bank statement. "
                    "Undo the bank reconciliation before modifying it."
                )
            )
        if not self.move_id.show_reset_to_draft_button:
            raise UserError(
                _(
                    "This payment cannot be reset to draft "
                    "(locked journal, hash, or cancel request)."
                )
            )
        lines = self._get_replace_reconciled_lines()
        if not lines:
            raise UserError(
                _(
                    "This payment is not reconciled with any invoice or bill. "
                    "The Register Payment wizard cannot be opened."
                )
            )
        return lines

    def _is_bank_statement_reconciled(self):
        """True only when liquidity is linked to a bank statement line.

        Do NOT use ``is_matched``: in many setups (non-reconcilable outstanding
        accounts, or bank account used directly as liquidity) Odoo sets
        ``is_matched=True`` even without any statement.
        """
        self.ensure_one()
        if self.reconciled_statement_ids:
            return True
        liquidity_lines, _counterpart, _writeoff = self._seek_for_lines()
        for line in liquidity_lines:
            others = (
                line.matched_debit_ids.debit_move_id
                | line.matched_credit_ids.credit_move_id
            )
            if others.statement_line_id:
                return True
        return False

    def _get_replace_reconciled_lines(self):
        """Return invoice/bill AMLs currently reconciled with this payment.

        Must be called while the payment is still posted and reconciled.
        """
        self.ensure_one()
        _liquidity, counterpart, _writeoff = self._seek_for_lines()
        other_lines = self.env["account.move.line"]
        for line in counterpart:
            other_lines |= line.matched_debit_ids.debit_move_id
            other_lines |= line.matched_credit_ids.credit_move_id
        other_lines -= counterpart
        return other_lines.filtered(
            lambda line: line.account_internal_type in ("receivable", "payable")
            and line.move_id.is_invoice(include_receipts=True)
        )

    def _snapshot_for_chatter(self):
        """Return a JSON-serializable snapshot of editable payment values."""
        self.ensure_one()
        _liquidity, _counterpart, writeoff_lines = self._seek_for_lines()
        snapshot = {
            "amount": self.amount,
            "date": fields.Date.to_string(self.date),
            "journal": self.journal_id.display_name,
            "payment_method": self.payment_method_line_id.display_name,
            "ref": self.ref or "",
            "currency": self.currency_id.display_name,
        }
        if writeoff_lines:
            snapshot["writeoff_account"] = writeoff_lines[0].account_id.display_name
            snapshot["writeoff_label"] = writeoff_lines[0].name or ""
        return snapshot

    def _prepare_replace_payment_vals(self):
        """Snapshot of editable payment values to prefill the wizard."""
        self.ensure_one()
        _liquidity, _counterpart, writeoff_lines = self._seek_for_lines()
        writeoff_vals = {}
        if len(writeoff_lines) == 1:
            writeoff_vals = {
                "writeoff_account_id": writeoff_lines.account_id.id,
                "writeoff_label": writeoff_lines.name or _("Write-Off"),
            }
        return {
            "journal_id": self.journal_id.id,
            "payment_date": self.date,
            "currency_id": self.currency_id.id,
            "payment_method_line_id": self.payment_method_line_id.id,
            "partner_bank_id": self.partner_bank_id.id,
            "amount": self.amount,
            "communication": self.ref or "",
            "writeoff_vals": writeoff_vals,
        }

    def _prepare_modify_payment_wizard_context(self, line_ids, extra_context=None):
        """Build context for account.payment.register."""
        self.ensure_one()
        context = {
            "active_model": "account.move.line",
            "active_ids": line_ids.ids,
            "active_id": line_ids[:1].id,
            "dont_redirect_to_payments": True,
        }
        if extra_context:
            context.update(extra_context)
        return context

    def _create_modify_payment_register(self, line_ids, payment_vals, extra_context):
        """Create and prefill the standard Register Payment wizard."""
        self.ensure_one()
        wizard = (
            self.env["account.payment.register"]
            .with_context(
                **self._prepare_modify_payment_wizard_context(
                    line_ids, extra_context
                )
            )
            .create({})
        )
        phase1 = {}
        if payment_vals.get("journal_id"):
            phase1["journal_id"] = payment_vals["journal_id"]
        if payment_vals.get("payment_date"):
            phase1["payment_date"] = payment_vals["payment_date"]
        if payment_vals.get("currency_id"):
            phase1["currency_id"] = payment_vals["currency_id"]
        if payment_vals.get("partner_bank_id"):
            phase1["partner_bank_id"] = payment_vals["partner_bank_id"]
        preferred_method = payment_vals.get("payment_method_line_id")
        if phase1:
            wizard.write(phase1)
        if preferred_method:
            method = wizard._resolve_payment_method_line(preferred_method)
            if method:
                wizard.payment_method_line_id = method
        wizard.write(
            {
                "amount": payment_vals["amount"],
                "communication": payment_vals.get("communication") or "",
            }
        )
        writeoff_vals = payment_vals.get("writeoff_vals") or {}
        partial_writeoff_vals = payment_vals.get("partial_writeoff_vals") or {}
        if partial_writeoff_vals:
            wizard.write(
                {
                    "payment_difference_handling": "open",
                    "post_difference_on_open": True,
                    "open_writeoff_account_id": partial_writeoff_vals[
                        "writeoff_account_id"
                    ],
                    "open_writeoff_label": partial_writeoff_vals.get(
                        "writeoff_label"
                    )
                    or _("Write-Off"),
                    "writeoff_amount": partial_writeoff_vals["writeoff_amount"],
                }
            )
            register_lines = payment_vals.get("register_writeoff_line_ids") or []
            if register_lines:
                wizard.write({"register_writeoff_line_ids": register_lines})
        elif writeoff_vals and not wizard.currency_id.is_zero(
            wizard.payment_difference
        ):
            wizard.write(
                {
                    "payment_difference_handling": "reconcile",
                    "writeoff_account_id": writeoff_vals["writeoff_account_id"],
                    "writeoff_label": writeoff_vals["writeoff_label"],
                }
            )
        if preferred_method:
            method = wizard._resolve_payment_method_line(preferred_method)
            if method:
                wizard.payment_method_line_id = method
        return wizard

    def _open_modify_payment_register(self, wizard):
        self.ensure_one()
        return {
            "name": _("Register Payment"),
            "type": "ir.actions.act_window",
            "res_model": "account.payment.register",
            "view_mode": "form",
            "views": [[False, "form"]],
            "target": "new",
            "res_id": wizard.id,
            "context": dict(self.env.context, **wizard.env.context),
        }

    def action_replace_payment(self):
        """Correct a posted payment via Register Payment prefilled."""
        self.ensure_one()
        mode = self.company_id.account_payment_modify_mode
        if mode == "edit":
            return self._action_edit_payment()
        return self._action_replace_payment()

    def _action_replace_payment(self):
        self.ensure_one()
        line_ids = self._check_can_modify("replace")
        payment_vals = self._prepare_replace_payment_vals()
        self.action_draft()
        self.action_cancel()
        wizard = self._create_modify_payment_register(
            line_ids,
            payment_vals,
            {"replaced_payment_id": self.id},
        )
        return self._open_modify_payment_register(wizard)

    def _action_edit_payment(self):
        self.ensure_one()
        line_ids = self._check_can_modify("edit")
        payment_vals = self._prepare_replace_payment_vals()
        old_vals = self._snapshot_for_chatter()
        self.action_draft()
        wizard = self._create_modify_payment_register(
            line_ids,
            payment_vals,
            {
                "edit_payment_id": self.id,
                "edit_payment_old_vals": old_vals,
            },
        )
        return self._open_modify_payment_register(wizard)

    def _sync_move_lines_from_writeoff(self, write_off_line_vals=None):
        """Regenerate draft move lines, optionally applying wizard write-off."""
        self.ensure_one()
        liquidity_lines, counterpart_lines, writeoff_lines = self._seek_for_lines()
        line_vals_list = self._prepare_move_line_default_vals(
            write_off_line_vals=write_off_line_vals or {}
        )
        line_ids_commands = [
            (1, liquidity_lines.id, line_vals_list[0])
            if liquidity_lines
            else (0, 0, line_vals_list[0]),
            (1, counterpart_lines.id, line_vals_list[1])
            if counterpart_lines
            else (0, 0, line_vals_list[1]),
        ]
        for line in writeoff_lines:
            line_ids_commands.append((2, line.id))
        for extra_line_vals in line_vals_list[2:]:
            line_ids_commands.append((0, 0, extra_line_vals))
        self.move_id.write({"line_ids": line_ids_commands})

    def _reconcile_after_edit(self, lines_to_reconcile):
        self.ensure_one()
        domain = [
            ("parent_state", "=", "posted"),
            ("account_internal_type", "in", ("receivable", "payable")),
            ("reconciled", "=", False),
        ]
        payment_lines = self.line_ids.filtered_domain(domain)
        for account in payment_lines.account_id:
            (
                payment_lines + lines_to_reconcile
            ).filtered_domain(
                [("account_id", "=", account.id), ("reconciled", "=", False)]
            ).reconcile()

    def _message_payment_edited(self, old_vals, new_vals):
        self.ensure_one()
        labels = {
            "amount": _("Amount"),
            "date": _("Date"),
            "journal": _("Journal"),
            "payment_method": _("Payment Method"),
            "ref": _("Memo"),
            "currency": _("Currency"),
            "writeoff_account": _("Write-Off Account"),
            "writeoff_label": _("Write-Off Label"),
        }
        changes = []
        for key, label in labels.items():
            old_value = old_vals.get(key, "")
            new_value = new_vals.get(key, "")
            if old_value != new_value:
                changes.append(
                    "<li><strong>%s</strong>: %s → %s</li>"
                    % (label, old_value, new_value)
                )
        if not changes:
            changes.append("<li>%s</li>" % _("No field changes detected."))
        body = _("Payment edited via Register Payment wizard:") + "<ul>%s</ul>" % (
            "".join(changes)
        )
        self.message_post(body=body)

    def _fix_payment_vals_method_line(self, payment_vals):
        """Ensure journal and payment method line stay consistent."""
        self.ensure_one()
        journal = self.env["account.journal"].browse(payment_vals["journal_id"])
        available = journal._get_available_payment_method_lines(
            payment_vals["payment_type"]
        )
        method = self.env["account.payment.method.line"].browse(
            payment_vals.get("payment_method_line_id")
        )
        if method not in available:
            method = available[:1]
        if method:
            payment_vals["payment_method_line_id"] = method.id
        return payment_vals

    def _apply_edit_from_wizard(self, wizard):
        """Update this draft payment from the wizard and post it."""
        self.ensure_one()
        if self.state != "draft":
            raise UserError(_("Only draft payments can be edited from the wizard."))

        payment_vals = wizard._create_payment_vals_from_wizard()
        write_off_line_vals = payment_vals.pop("write_off_line_vals", None)
        payment_vals = self._fix_payment_vals_method_line(payment_vals)

        old_vals = dict(self.env.context.get("edit_payment_old_vals") or {})
        self.write(payment_vals)
        self._sync_move_lines_from_writeoff(write_off_line_vals or {})

        self.action_post()
        # Partial write-off modules reconcile in action_post; skip if already done.
        unreconciled = self.line_ids.filtered_domain(
            [
                ("parent_state", "=", "posted"),
                ("account_internal_type", "in", ("receivable", "payable")),
                ("reconciled", "=", False),
            ]
        )
        if unreconciled:
            lines_to_reconcile = wizard._get_batches()[0]["lines"]
            self._reconcile_after_edit(lines_to_reconcile)
        self._message_payment_edited(old_vals, self._snapshot_for_chatter())
        return self

    def _link_from_replaced_payment(self, replaced_payment):
        """Link new payments to the cancelled original and post chatter."""
        replaced_payment.ensure_one()
        if not self:
            return
        if len(self) > 1:
            raise UserError(
                _(
                    "Payment replace expects a single new payment. "
                    "Disable grouping or select one invoice batch."
                )
            )
        new_payment = self
        if replaced_payment.replacement_payment_id:
            raise UserError(
                _("Payment %s was already replaced.")
                % replaced_payment.display_name
            )
        new_payment.replaced_payment_id = replaced_payment
        replaced_payment.replacement_payment_id = new_payment
        replaced_payment.message_post(
            body=_("This payment was replaced by %s") % new_payment.display_name
        )
        new_payment.message_post(
            body=_("This payment replaces payment %s")
            % replaced_payment.display_name
        )
