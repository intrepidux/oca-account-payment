# Copyright 2026 Intrepidux
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    account_payment_modify_mode = fields.Selection(
        related="company_id.account_payment_modify_mode",
        readonly=False,
    )
