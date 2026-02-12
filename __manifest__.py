{
    'name': 'sid_projects_dossier',
    'version': '1.1.0',
    'category': 'Sales',
    'license': 'AGPL-3',
    'summary': 'Control de Base Imponible',
    'description': 'Módulo de gestión de Dossieres de Calidad',
    'author': 'oscarsidsa81',
    'depends': ['base','crm','sale_management','documents','oct_sale_extra_fields'],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/document_group.xml',
        'data/documents_tags.xml',

        # Wizard actions/views must be loaded before views referencing them
        'data/sid_dossier_assign_wizard.xml',

        # Views / menus
        'views/sid_projects_dossier_sales.xml',
        'views/sid_projects_dossier_quotations.xml',

        # Window actions / menus
        'data/document_actions.xml',
    ],
    'installable': True,
    'auto_install': False,
    'application': False,

    # Vincular estructura existente: "Dossieres de calidad" (root) y años
    'post_init_hook': 'post_init_bind_quality_dossiers_folders',
}