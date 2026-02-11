# -*- coding: utf-8 -*-
{
    "name": "sid_bankbonds_mod",
    "summary": "Gestión de avales con contratos vinculados, estados y chatter",
    "version": "15.0.1.0.0",
    "author": "oscarsidsa81",
    "website": "https://sid-sa.com",
    "category": "Accounting/Finance",
    "license": "AGPL-3",
    "depends": ["base", "mail", "purchase", "account", "sale","documents","oct_sale_extra_fields"],  # sale por sale.order; account por account.journal
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/automation.xml",
        'views/sale_quotations_views.xml',
        'views/sale_quotations_action_menu.xml',
        "views/bonds_views.xml",
    ],
    'installable' : True,
    'auto_install' : False,
    'application' : False,

    # Migración automática desde el modelo Studio (si existe): x_bonds.orders
    'post_init_hook': 'post_init_migrate_from_studio',
}