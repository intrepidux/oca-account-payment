# Copyright 2026 Glowicom
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

{
    "name": "Account Payment Partial Write-Off",
    "version": "15.0.1.0.2",
    "category": "Accounting",
    "summary": "Partial payment write-off under Keep open on payments and register wizard",
    "author": "Glowicom, Odoo Community Association (OCA)",
    "website": "https://github.com/OCA/account-payment",
    "license": "AGPL-3",
    "depends": ["account"],
    "data": [
        "security/ir.model.access.csv",
        "views/account_payment_views.xml",
        "views/account_payment_register_views.xml",
    ],
    "installable": True,
    "application": False,
    "development_status": "Beta",
}
