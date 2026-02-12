# -*- coding: utf-8 -*-

from odoo import api, fields, models


class SaleOrderDossier(models.Model):
    _inherit = 'sale.order'

    # Visible/agrupable en sale.order, pero el vínculo vive en sale.quotations
    dossier_folder_id = fields.Many2one(
        comodel_name='documents.folder',
        string='Dossier (carpeta)',
        related='quotations_id.dossier_folder_id',
        store=True,
        readonly=True,
    )
    dossier_asignado = fields.Char(
        string='Dossier asignado',
        compute='_compute_dossier_asignado',
        store=True,
        readonly=True,
    )
    tiene_dossier = fields.Boolean(
        string='Dossier activo',
        compute='_compute_tiene_dossier',
        store=True,
        readonly=True,
    )

    @api.depends('dossier_folder_id')
    def _compute_tiene_dossier(self):
        for so in self:
            so.tiene_dossier = bool(so.dossier_folder_id)

    @api.depends('dossier_folder_id', 'dossier_folder_id.name')
    def _compute_dossier_asignado(self):
        for so in self:
            so.dossier_asignado = so.dossier_folder_id.name if so.dossier_folder_id else ''

    def action_open_dossier_wizard_create(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Crear dossier',
            'res_model': 'sid.dossier.assign.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_sale_order_id': self.id,
                'default_quotation_id': self.quotations_id.id if self.quotations_id else False,
                'default_mode': 'new',
            },
        }

    def action_open_dossier_wizard_link(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Vincular dossier',
            'res_model': 'sid.dossier.assign.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_sale_order_id': self.id,
                'default_quotation_id': self.quotations_id.id if self.quotations_id else False,
                'default_mode': 'existing',
            },
        }

    def action_view_dossier(self):
        self.ensure_one()
        if not self.dossier_folder_id:
            return self.action_open_dossier_wizard_link()
        return {
            'type': 'ir.actions.act_window',
            'name': self.dossier_folder_id.display_name,
            'res_model': 'documents.folder',
            'view_mode': 'form',
            'res_id': self.dossier_folder_id.id,
            'target': 'current',
        }


class DocumentsDocumentDossier(models.Model):
    _inherit = 'documents.document'

    dossier_contrato = fields.Char(
        string='Dossier (contrato)',
        compute='_compute_dossier_contrato',
        store=True,
        readonly=True,
        help='Carpeta de dossier (nivel 2) a la que cuelga el documento.',
    )

    document_description = fields.Char(string='Descripción', store=True)
    document_transmittal = fields.Char(string='Transmittal', store=True)

    @api.depends('folder_id', 'folder_id.parent_folder_id', 'folder_id.parent_folder_id.parent_folder_id')
    def _compute_dossier_contrato(self):
        root = self.env.ref('sid_projects_dossier.sid_workspace_quality_dossiers', raise_if_not_found=False)
        for doc in self:
            dossier_folder = False
            folder = doc.folder_id
            while folder and folder.parent_folder_id:
                # Dossier folder is the one whose grandparent is the root
                if root and folder.parent_folder_id.parent_folder_id and folder.parent_folder_id.parent_folder_id.id == root.id:
                    dossier_folder = folder
                    break
                folder = folder.parent_folder_id
            doc.dossier_contrato = dossier_folder.name if dossier_folder else ''
