# -*- coding: utf-8 -*-

from datetime import date

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class SidDossierAssignWizard(models.TransientModel):
    _name = 'sid.dossier.assign.wizard'
    _description = 'Crear/Vincular dossier de calidad'

    sale_order_id = fields.Many2one('sale.order', string='Pedido', readonly=True)
    quotation_id = fields.Many2one('sale.quotations', string='Presupuesto/Contrato', required=True)

    contract_kind = fields.Selection(
        selection=[('principal', 'Contrato principal'), ('adenda', 'Adenda')],
        string='Tipo',
        required=True,
        default='principal',
    )

    mode = fields.Selection(
        selection=[('new', 'Crear dossier nuevo'), ('existing', 'Vincular dossier existente')],
        string='Operación',
        required=True,
        default='new',
    )

    principal_quotation_id = fields.Many2one(
        'sale.quotations',
        string='Contrato principal',
        domain="[('parent_id','=',False)]",
    )

    existing_folder_id = fields.Many2one(
        'documents.folder',
        string='Dossier existente (nivel 2)',
        domain=[],
    )

    new_folder_name = fields.Char(string='Nombre del dossier', readonly=True)

    warning_message = fields.Text(string='Aviso', readonly=True)

    # ---------------------------------------------------------------------
    # Helpers: root/year folders
    # ---------------------------------------------------------------------

    def _get_root_folder(self):
        root = self.env.ref('sid_projects_dossier.folder_root_dossieres_calidad', raise_if_not_found=False)
        if root:
            return root
        # Fallback by name
        return self.env['documents.folder'].sudo().search([
            ('name', '=', 'Dossieres de calidad'),
            ('parent_folder_id', '=', False)
        ], limit=1)

    def _ensure_year_folder(self, year_int: int):
        root = self._get_root_folder()
        if not root:
            raise UserError(_('No se ha encontrado el root "Dossieres de calidad" en Documentos.'))
        Folder = self.env['documents.folder'].sudo()
        yname = str(year_int)
        year_folder = Folder.search([('parent_folder_id', '=', root.id), ('name', '=', yname)], limit=1)
        if not year_folder:
            year_folder = Folder.create({'name': yname, 'parent_folder_id': root.id})
        return year_folder

    def _folder_has_documents(self, folder):
        Doc = self.env['documents.document'].sudo()
        return bool(Doc.search_count([('folder_id', '=', folder.id)]))

    def _folder_linked_to_other_contract(self, folder, root_quotation):
        Q = self.env['sale.quotations'].sudo()
        other = Q.search([
            ('dossier_folder_id', '=', folder.id),
            ('id', '!=', root_quotation.id),
        ], limit=1)
        return other

    # ---------------------------------------------------------------------
    # Onchange / defaults
    # ---------------------------------------------------------------------

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)

        qid = res.get('quotation_id')
        if qid:
            q = self.env['sale.quotations'].browse(qid).exists()
            if q:
                root = q.dossier_root_id or q
                res['new_folder_name'] = root.name
                # default contract_kind from relationship
                res['contract_kind'] = 'principal' if not q.parent_id else 'adenda'

                if res.get('contract_kind') == 'adenda':
                    res['principal_quotation_id'] = root.id
                    if root.dossier_folder_id:
                        res['mode'] = 'existing'
                        res['existing_folder_id'] = root.dossier_folder_id.id

        return res

    @api.onchange('quotation_id')
    def _onchange_quotation(self):
        if not self.quotation_id:
            return
        root = self.quotation_id.dossier_root_id or self.quotation_id
        self.new_folder_name = root.name
        self.contract_kind = 'principal' if not self.quotation_id.parent_id else 'adenda'
        if self.contract_kind == 'adenda':
            self.principal_quotation_id = root
            if root.dossier_folder_id:
                self.mode = 'existing'
                self.existing_folder_id = root.dossier_folder_id

    @api.onchange('contract_kind')
    def _onchange_contract_kind(self):
        if not self.quotation_id:
            return
        root = self.quotation_id.dossier_root_id or self.quotation_id
        if self.contract_kind == 'adenda':
            self.principal_quotation_id = root
            if root.dossier_folder_id:
                self.mode = 'existing'
                self.existing_folder_id = root.dossier_folder_id

    @api.onchange('mode', 'existing_folder_id', 'principal_quotation_id', 'quotation_id')
    def _onchange_warnings(self):
        self.warning_message = False
        if self.mode != 'existing' or not self.existing_folder_id:
            return

        # Evaluate warnings
        q = self.quotation_id
        if not q:
            return
        root_q = (q.dossier_root_id or q) if self.contract_kind != 'adenda' else (self.principal_quotation_id or q.dossier_root_id or q)

        msgs = []
        if self._folder_has_documents(self.existing_folder_id):
            msgs.append(_('La carpeta seleccionada ya contiene documentos. Se recomienda NO reasignar salvo que sea intencionado.'))

        other = self._folder_linked_to_other_contract(self.existing_folder_id, root_q)
        if other:
            msgs.append(_('La carpeta ya está vinculada al contrato: %s') % (other.display_name or other.name))

        self.warning_message = '\n'.join(msgs) if msgs else False

    # Dynamic domain for existing_folder_id (nivel 2 de todos los años)
    @api.onchange('quotation_id')
    def _onchange_existing_folder_domain(self):
        root = self._get_root_folder()
        if root:
            return {
                'domain': {
                    'existing_folder_id': [('parent_folder_id.parent_folder_id', '=', root.id)],
                }
            }
        return {
            'domain': {'existing_folder_id': []}
        }

    # ---------------------------------------------------------------------
    # Confirm
    # ---------------------------------------------------------------------

    def action_confirm(self):
        self.ensure_one()
        if not self.quotation_id:
            raise UserError(_('Seleccione un presupuesto/contrato.'))

        root_q = self.quotation_id.dossier_root_id or self.quotation_id
        if self.contract_kind == 'adenda':
            if not self.principal_quotation_id:
                raise UserError(_('Seleccione el contrato principal.'))
            root_q = self.principal_quotation_id.dossier_root_id or self.principal_quotation_id

        Folder = self.env['documents.folder'].sudo()

        if self.mode == 'existing':
            if not self.existing_folder_id:
                raise UserError(_('Seleccione una carpeta de dossier existente.'))
            root_q.sudo().write({'dossier_folder_id': self.existing_folder_id.id})

        else:
            # Create or reuse dossier folder under current year
            year_folder = self._ensure_year_folder(date.today().year)
            dossier_name = (self.new_folder_name or root_q.name or '').strip()
            if not dossier_name:
                raise UserError(_('No se pudo determinar el nombre del dossier.'))

            dossier_folder = Folder.search([
                ('parent_folder_id', '=', year_folder.id),
                ('name', '=', dossier_name),
            ], limit=1)
            if not dossier_folder:
                dossier_folder = Folder.create({'name': dossier_name, 'parent_folder_id': year_folder.id})

            root_q.sudo().write({'dossier_folder_id': dossier_folder.id})

        # Optional: chatter note (if mail.thread available)
        try:
            msg = _('Dossier asignado: %s') % (root_q.dossier_folder_id.display_name)
            root_q.message_post(body=msg)
        except Exception:
            pass

        return {'type': 'ir.actions.act_window_close'}
