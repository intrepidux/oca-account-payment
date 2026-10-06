# Copyright 2026 Glowicom
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import fields
from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.tests import tagged


@tagged("post_install", "-at_install")
class TestPartialWriteoff(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls, chart_template_ref=None):
        super().setUpClass(chart_template_ref=chart_template_ref)
        cls.partner = cls.env["res.partner"].create({"name": "Writeoff Partner"})
        cls.product = cls.env["product.product"].create(
            {
                "name": "Writeoff Product",
                "list_price": 1200.0,
                "type": "service",
                "property_account_income_id": cls.company_data[
                    "default_account_revenue"
                ].id,
            }
        )
        cls.bank_journal = cls.company_data["default_journal_bank"]
        cls.sale_journal = cls.company_data["default_journal_sale"]
        cls.expense_account = cls.company_data["default_account_expense"]

    def _create_invoice(self, amount=1200.0):
        invoice = self.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "partner_id": self.partner.id,
                "journal_id": self.sale_journal.id,
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
        invoice.action_post()
        return invoice

    def test_partial_writeoff_payment_residual(self):
        invoice = self._create_invoice()
        payment = self.env["account.payment"].create(
            {
                "payment_type": "inbound",
                "partner_type": "customer",
                "partner_id": self.partner.id,
                "amount": 585.0,
                "journal_id": self.bank_journal.id,
                "payment_difference_handling": "open",
                "post_difference_on_open": True,
                "writeoff_account_id": self.expense_account.id,
                "writeoff_label": "Bank fee",
                "writeoff_amount": 15.0,
                "payment_writeoff_line_ids": [
                    (
                        0,
                        0,
                        {
                            "invoice_id": invoice.id,
                            "add_invoice": True,
                            "allocated_amount": 585.0,
                        },
                    )
                ],
            }
        )
        payment.action_post()

        self.assertAlmostEqual(invoice.amount_residual, 600.0, places=2)
        liquidity_lines, counterpart_lines, writeoff_lines = payment._seek_for_lines()
        self.assertEqual(len(writeoff_lines), 1)
        self.assertAlmostEqual(abs(sum(counterpart_lines.mapped("balance"))), 600.0, places=2)
        self.assertAlmostEqual(sum(liquidity_lines.mapped("balance")), 585.0, places=2)

    def test_register_wizard_partial_writeoff(self):
        invoice = self._create_invoice()
        wizard = (
            self.env["account.payment.register"]
            .with_context(active_model="account.move", active_ids=invoice.ids)
            .create(
                {
                    "amount": 585.0,
                    "payment_difference_handling": "open",
                    "post_difference_on_open": True,
                    "open_writeoff_account_id": self.expense_account.id,
                    "open_writeoff_label": "Bank fee",
                    "writeoff_amount": 15.0,
                    "register_writeoff_line_ids": [
                        (
                            0,
                            0,
                            {
                                "invoice_id": invoice.id,
                                "add_invoice": True,
                                "allocated_amount": 585.0,
                            },
                        )
                    ],
                }
            )
        )
        payment = wizard._create_payments()
        self.assertTrue(payment.post_difference_on_open)
        self.assertAlmostEqual(payment.writeoff_amount, 15.0, places=2)
        self.assertAlmostEqual(payment.amount, 585.0, places=2)

    def test_open_without_writeoff_unchanged(self):
        invoice = self._create_invoice()
        payment = self.env["account.payment"].create(
            {
                "payment_type": "inbound",
                "partner_type": "customer",
                "partner_id": self.partner.id,
                "amount": 585.0,
                "journal_id": self.bank_journal.id,
                "payment_difference_handling": "open",
                "payment_writeoff_line_ids": [
                    (
                        0,
                        0,
                        {
                            "invoice_id": invoice.id,
                            "add_invoice": True,
                            "allocated_amount": 585.0,
                        },
                    )
                ],
            }
        )
        payment.action_post()
        self.assertAlmostEqual(invoice.amount_residual, 615.0, places=2)
