# Copyright 2026 Intrepidux
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import fields
from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.exceptions import UserError
from odoo.tests import tagged


@tagged("post_install", "-at_install")
class TestAccountPaymentReplace(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls, chart_template_ref=None):
        super().setUpClass(chart_template_ref=chart_template_ref)
        cls.env = cls.env(
            context=dict(
                cls.env.context,
                mail_create_nolog=True,
                mail_notrack=True,
                tracking_disable=True,
            )
        )
        cls.partner = cls.env["res.partner"].create({"name": "Replace Partner"})
        cls.product = cls.env["product.product"].create(
            {
                "name": "Replace Product",
                "list_price": 100.0,
                "type": "service",
                "property_account_income_id": cls.company_data[
                    "default_account_revenue"
                ].id,
                "property_account_expense_id": cls.company_data[
                    "default_account_expense"
                ].id,
            }
        )
        cls.bank_journal = cls.company_data["default_journal_bank"]
        cls.sale_journal = cls.company_data["default_journal_sale"]
        cls.purchase_journal = cls.company_data["default_journal_purchase"]
        cls.expense_account = cls.company_data["default_account_expense"]

    def _set_modify_mode(self, mode):
        self.env.company.account_payment_modify_mode = mode

    def _run_modify(self, payment, amount=None):
        action = payment.action_replace_payment()
        wizard = self._wizard_from_action(action)
        if amount is not None:
            wizard.amount = amount
        return wizard._create_payments()

    def _create_invoice(self, move_type="out_invoice", amount=100.0, post=True):
        journal = (
            self.sale_journal
            if move_type.startswith("out_")
            else self.purchase_journal
        )
        invoice = self.env["account.move"].create(
            {
                "move_type": move_type,
                "partner_id": self.partner.id,
                "journal_id": journal.id,
                "invoice_date": fields.Date.today(),
                "invoice_line_ids": [
                    (
                        0,
                        0,
                        {
                            "product_id": self.product.id,
                            "quantity": 1.0,
                            "price_unit": amount,
                            "tax_ids": False,
                        },
                    )
                ],
            }
        )
        if post:
            invoice.action_post()
        return invoice

    def _register_payment(self, invoices, amount=None, **extra):
        wizard = (
            self.env["account.payment.register"]
            .with_context(
                active_model="account.move",
                active_ids=invoices.ids,
            )
            .create(
                {
                    "journal_id": self.bank_journal.id,
                    **({"amount": amount} if amount is not None else {}),
                    **extra,
                }
            )
        )
        return wizard._create_payments()

    def _wizard_from_action(self, action):
        """Browse wizard keeping replaced_payment_id context from the action."""
        self.assertEqual(action["res_model"], "account.payment.register")
        ctx = dict(action.get("context") or {})
        wizard = (
            self.env["account.payment.register"]
            .with_context(**ctx)
            .browse(action["res_id"])
        )
        self.assertTrue(wizard.exists())
        return wizard

    def _run_replace(self, payment, amount=None):
        return self._run_modify(payment, amount=amount)

    def test_replace_inbound_full_payment(self):
        invoice = self._create_invoice(amount=150.0)
        payment = self._register_payment(invoice)
        self.assertEqual(payment.state, "posted")
        self.assertEqual(invoice.payment_state, "paid")

        new_payment = self._run_replace(payment)
        self.assertEqual(payment.state, "cancel")
        self.assertEqual(new_payment.state, "posted")
        self.assertEqual(new_payment.replaced_payment_id, payment)
        self.assertEqual(payment.replacement_payment_id, new_payment)
        self.assertEqual(new_payment.amount, 150.0)
        self.assertEqual(new_payment.journal_id, payment.journal_id)
        invoice.invalidate_cache()
        self.assertEqual(invoice.payment_state, "paid")

    def test_replace_from_invoice(self):
        invoice = self._create_invoice(amount=110.0)
        payment = self._register_payment(invoice)
        action = invoice.action_replace_payment()
        wizard = self._wizard_from_action(action)
        new_payment = wizard._create_payments()
        self.assertEqual(payment.state, "cancel")
        self.assertEqual(new_payment.replaced_payment_id, payment)

    def test_replace_partial_with_amount_change(self):
        invoice = self._create_invoice(amount=200.0)
        payment = self._register_payment(invoice, amount=80.0)
        self.assertEqual(invoice.payment_state, "partial")

        new_payment = self._run_replace(payment, amount=120.0)
        self.assertEqual(payment.state, "cancel")
        self.assertEqual(new_payment.amount, 120.0)
        self.assertEqual(new_payment.replaced_payment_id, payment)
        invoice.invalidate_cache()
        self.assertEqual(invoice.payment_state, "partial")

    def test_replace_outbound_vendor_bill(self):
        bill = self._create_invoice(move_type="in_invoice", amount=90.0)
        payment = self._register_payment(bill)
        self.assertEqual(payment.payment_type, "outbound")

        new_payment = self._run_replace(payment)
        self.assertEqual(payment.state, "cancel")
        self.assertEqual(new_payment.payment_type, "outbound")
        self.assertEqual(new_payment.replaced_payment_id, payment)
        bill.invalidate_cache()
        self.assertEqual(bill.payment_state, "paid")

    def test_replace_multi_invoice_grouped(self):
        inv1 = self._create_invoice(amount=50.0)
        inv2 = self._create_invoice(amount=70.0)
        payment = self._register_payment(inv1 | inv2, group_payment=True)
        self.assertEqual(len(payment), 1)
        self.assertAlmostEqual(payment.amount, 120.0)

        new_payment = self._run_replace(payment)
        self.assertEqual(payment.state, "cancel")
        self.assertEqual(new_payment.replaced_payment_id, payment)
        self.assertAlmostEqual(new_payment.amount, 120.0)
        for inv in inv1 | inv2:
            inv.invalidate_cache()
            self.assertEqual(inv.payment_state, "paid")

    def test_replace_with_writeoff_prefill(self):
        invoice = self._create_invoice(amount=100.0)
        payment = self._register_payment(
            invoice,
            amount=95.0,
            payment_difference_handling="reconcile",
            writeoff_account_id=self.expense_account.id,
            writeoff_label="Bank fee",
        )
        self.assertEqual(invoice.payment_state, "paid")

        action = payment.action_replace_payment()
        wizard = self._wizard_from_action(action)
        self.assertAlmostEqual(wizard.amount, 95.0)
        self.assertEqual(wizard.payment_difference_handling, "reconcile")
        self.assertEqual(wizard.writeoff_account_id, self.expense_account)
        self.assertEqual(wizard.writeoff_label, "Bank fee")

        new_payment = wizard._create_payments()
        self.assertEqual(new_payment.replaced_payment_id, payment)
        invoice.invalidate_cache()
        self.assertEqual(invoice.payment_state, "paid")

    def test_block_already_replaced(self):
        invoice = self._create_invoice(amount=40.0)
        payment = self._register_payment(invoice)
        self._run_replace(payment)
        with self.assertRaises(UserError):
            payment.action_replace_payment()

    def test_block_draft_payment(self):
        invoice = self._create_invoice(amount=40.0)
        payment = self._register_payment(invoice)
        payment.action_draft()
        with self.assertRaises(UserError):
            payment.action_replace_payment()

    def test_block_unreconciled_payment(self):
        payment = self.env["account.payment"].create(
            {
                "payment_type": "inbound",
                "partner_type": "customer",
                "partner_id": self.partner.id,
                "amount": 25.0,
                "journal_id": self.bank_journal.id,
            }
        )
        payment.action_post()
        with self.assertRaises(UserError):
            payment.action_replace_payment()

    def test_block_internal_transfer(self):
        cash_journal = self.company_data["default_journal_cash"]
        if not cash_journal or not self.bank_journal:
            self.skipTest("Need bank and cash journals")
        company_partner = self.env.company.partner_id
        payment = self.env["account.payment"].create(
            {
                "payment_type": "outbound",
                "partner_id": company_partner.id,
                "amount": 10.0,
                "journal_id": self.bank_journal.id,
                "destination_journal_id": cash_journal.id,
            }
        )
        if not payment.is_internal_transfer:
            self.skipTest("Internal transfer not available in this setup")
        payment.action_post()
        with self.assertRaises(UserError):
            payment.action_replace_payment()

    def test_wizard_prefills_ref_and_date(self):
        invoice = self._create_invoice(amount=55.0)
        payment = self._register_payment(
            invoice,
            communication="MEMO-XYZ",
        )
        self.assertTrue(payment.ref or payment.date)

        action = payment.action_replace_payment()
        wizard = self._wizard_from_action(action)
        self.assertEqual(wizard.payment_date, payment.date)
        self.assertEqual(wizard.journal_id, self.bank_journal)
        if payment.ref:
            self.assertEqual(wizard.communication, payment.ref)

    def test_default_mode_is_replace(self):
        self.assertEqual(
            self.env.company.account_payment_modify_mode,
            "replace",
        )

    def test_company_setting_switches_to_edit(self):
        self._set_modify_mode("edit")
        self.assertEqual(self.env.company.account_payment_modify_mode, "edit")

    def test_edit_keeps_same_record(self):
        self._set_modify_mode("edit")
        invoice = self._create_invoice(amount=150.0)
        payment = self._register_payment(invoice)
        payment_id = payment.id

        result = self._run_modify(payment)
        self.assertEqual(result.id, payment_id)
        self.assertEqual(payment.state, "posted")
        self.assertFalse(payment.replaced_payment_id)
        self.assertFalse(payment.replacement_payment_id)
        invoice.invalidate_cache()
        self.assertEqual(invoice.payment_state, "paid")

    def test_edit_with_amount_change(self):
        self._set_modify_mode("edit")
        invoice = self._create_invoice(amount=200.0)
        payment = self._register_payment(invoice, amount=80.0)
        payment_id = payment.id

        result = self._run_modify(payment, amount=120.0)
        self.assertEqual(result.id, payment_id)
        self.assertEqual(payment.state, "posted")
        self.assertAlmostEqual(payment.amount, 120.0)
        invoice.invalidate_cache()
        self.assertEqual(invoice.payment_state, "partial")

    def test_edit_with_writeoff_prefill(self):
        self._set_modify_mode("edit")
        invoice = self._create_invoice(amount=100.0)
        payment = self._register_payment(
            invoice,
            amount=95.0,
            payment_difference_handling="reconcile",
            writeoff_account_id=self.expense_account.id,
            writeoff_label="Bank fee",
        )

        action = payment.action_replace_payment()
        wizard = self._wizard_from_action(action)
        self.assertAlmostEqual(wizard.amount, 95.0)
        self.assertEqual(wizard.payment_difference_handling, "reconcile")
        self.assertEqual(wizard.writeoff_account_id, self.expense_account)
        self.assertEqual(wizard.writeoff_label, "Bank fee")

        result = wizard._create_payments()
        self.assertEqual(result, payment)
        invoice.invalidate_cache()
        self.assertEqual(invoice.payment_state, "paid")

    def test_edit_chatter_diff(self):
        self._set_modify_mode("edit")
        invoice = self._create_invoice(amount=100.0)
        payment = self._register_payment(invoice, amount=100.0)

        wizard = self._wizard_from_action(payment.action_replace_payment())
        wizard.amount = 90.0
        wizard._create_payments()

        messages = payment.message_ids.filtered(
            lambda message: "Payment edited via Register Payment wizard" in (
                message.body or ""
            )
        )
        self.assertTrue(messages)
        self.assertIn("100.0", messages[0].body)
        self.assertIn("90.0", messages[0].body)

    def test_edit_abandoned_wizard_leaves_draft(self):
        self._set_modify_mode("edit")
        invoice = self._create_invoice(amount=60.0)
        payment = self._register_payment(invoice)
        payment.action_replace_payment()
        self.assertEqual(payment.state, "draft")
