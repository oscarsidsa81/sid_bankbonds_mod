# -*- coding: utf-8 -*-

from datetime import date

from odoo import api, SUPERUSER_ID


def _bind_xml(env, folder, module, name):
    """Create/update an xml_id pointing to an existing documents.folder."""
    IMD = env['ir.model.data'].sudo()
    imd = IMD.search([('module', '=', module), ('name', '=', name)], limit=1)
    vals = {
        'module': module,
        'name': name,
        'model': 'documents.folder',
        'res_id': folder.id,
        'noupdate': True,
    }
    if imd:
        imd.write(vals)
    else:
        IMD.create(vals)


def post_init_bind_quality_dossiers_folders(cr, registry):
    """Bind existing folder structure (root + year folders) to stable xml_ids."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    Folder = env['documents.folder'].sudo()

    module = 'sid_projects_dossier'

    # 1) Root folder
    root = Folder.search([('name', '=', 'Dossieres de calidad'), ('parent_folder_id', '=', False)], limit=1)
    if not root:
        # If not found we do nothing: module can still work but won't be able to filter by root.
        return

    # Backward/forward stable xml_id used by code
    _bind_xml(env, root, module, 'sid_workspace_quality_dossiers')
    # Friendly alias (optional)
    _bind_xml(env, root, module, 'folder_root_dossieres_calidad')

    # 2) Existing year folders (children of root)
    years = Folder.search([('parent_folder_id', '=', root.id)], order='name')
    for y in years:
        if y.name and y.name.isdigit() and len(y.name) == 4:
            _bind_xml(env, y, module, f'folder_year_{y.name}')

    # 3) Ensure current year folder exists
    current_year = str(date.today().year)
    ycur = Folder.search([('parent_folder_id', '=', root.id), ('name', '=', current_year)], limit=1)
    if not ycur:
        ycur = Folder.create({'name': current_year, 'parent_folder_id': root.id})
    _bind_xml(env, ycur, module, f'folder_year_{current_year}')
