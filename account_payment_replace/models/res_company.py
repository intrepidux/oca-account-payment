# Copyright 2026 Intrepidux
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    account_payment_modify_mode = fields.Selection(
        selection=[
            ("replace", "Replace payment (cancel and create new)"),
            ("edit", "Edit payment (keep same record)"),
        ],
        string="Payment Modify Mode",
        default="replace",
        required=True,
        help="How posted payments are corrected via the Register Payment wizard.",
    )
