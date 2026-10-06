# Copyright 2026 Intrepidux
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

{
    "name": "Account Payment Replace",
    "version": "15.0.2.0.0",
    "category": "Accounting",
    "summary": "Edit or replace posted payments via Register Payment prefilled",
    "author": "Intrepidux, Odoo Community Association (OCA)",
    "website": "https://github.com/OCA/account-payment",
    "license": "AGPL-3",
    "depends": ["account"],
    "data": [
        "security/security.xml",
        "views/res_config_settings_views.xml",
        "views/account_payment_views.xml",
        "views/account_move_views.xml",
    ],
    "installable": True,
    "application": False,
    "development_status": "Beta",
    "maintainers": ["intrepidux"],
}
