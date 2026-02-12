# -*- coding: utf-8 -*-

from datetime import date

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class SaleQuotationsDossier(models.Model):
    _inherit = 'sale.quotations'

    dossier_root_id = fields.Many2one(
        comodel_name='sale.quotations',
        string='Contrato principal',
        compute='_compute_dossier_root_id',
        store=True,
        readonly=True,
    )

    dossier_folder_id = fields.Many2one(
        comodel_name='documents.folder',
        string='Dossier',
        help='Carpeta (nivel 2) donde vive el dossier del contrato principal.',
    )

    dossier_state = fields.Selection(
        selection=[
            ('suministro', 'Suministro'),
            ('en_proceso', 'En proceso'),
            ('enviado', 'Enviado'),
            ('aprobado', 'Aprobado'),
        ],
        string='Estado del dossier',
        default='en_proceso',
        tracking=True,
    )

    has_dossier = fields.Boolean(
        string='Tiene dossier',
        compute='_compute_has_dossier',
        store=True,
        readonly=True,
    )

    @api.depends('parent_id')
    def _compute_dossier_root_id(self):
        for q in self:
            root = q
            seen = set()
            while root.parent_id and root.id not in seen:
                seen.add(root.id)
                root = root.parent_id
            q.dossier_root_id = root

    @api.depends('dossier_folder_id', 'dossier_root_id', 'dossier_root_id.dossier_folder_id')
    def _compute_has_dossier(self):
        for q in self:
            root = q.dossier_root_id or q
            q.has_dossier = bool(root.dossier_folder_id)

    # ---------------------------------------------------------------------
    # Actions
    # ---------------------------------------------------------------------

    def action_view_dossier(self):
        self.ensure_one()
        root = self.dossier_root_id or self
        folder = root.dossier_folder_id
        if not folder:
            raise UserError(_('Este contrato no tiene dossier asignado. Use "Crear dossier" o "Vincular dossier".'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Dossier'),
            'res_model': 'documents.folder',
            'view_mode': 'form',
            'res_id': folder.id,
            'target': 'current',
        }

    def action_open_dossier_wizard_create(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Crear dossier'),
            'res_model': 'sid.dossier.assign.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_sale_order_id': False,
                'default_quotation_id': self.id,
                'default_contract_kind': 'principal' if not self.parent_id else 'adenda',
                'default_mode': 'new',
            },
        }

    def action_open_dossier_wizard_link(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Vincular dossier'),
            'res_model': 'sid.dossier.assign.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_sale_order_id': False,
                'default_quotation_id': self.id,
                'default_contract_kind': 'principal' if not self.parent_id else 'adenda',
                'default_mode': 'existing',
            },
        }


class SaleOrderDossierRelated(models.Model):
    _inherit = 'sale.order'

    dossier_folder_id = fields.Many2one(
        comodel_name='documents.folder',
        string='Dossier',
        related='quotations_id.dossier_root_id.dossier_folder_id',
        store=True,
        readonly=True,
    )

    dossier_asignado = fields.Char(
        string='Dossier asignado',
        related='quotations_id.dossier_root_id.name',
        store=True,
        readonly=True,
    )

    tiene_dossier = fields.Boolean(
        string='Tiene dossier',
        compute='_compute_tiene_dossier',
        store=True,
        readonly=True,
    )

    @api.depends('dossier_folder_id')
    def _compute_tiene_dossier(self):
        for so in self:
            so.tiene_dossier = bool(so.dossier_folder_id)

    def action_view_dossier(self):
        self.ensure_one()
        folder = self.dossier_folder_id
        if not folder:
            # Open wizard (link/create) instead of raising to speed up user flow
            return {
                'type': 'ir.actions.act_window',
                'name': _('Asignar dossier'),
                'res_model': 'sid.dossier.assign.wizard',
                'view_mode': 'form',
                'target': 'new',
                'context': {
                    'default_sale_order_id': self.id,
                    'default_quotation_id': self.quotations_id.id if self.quotations_id else False,
                    'default_contract_kind': 'principal' if (self.quotations_id and not self.quotations_id.parent_id) else 'adenda',
                    'default_mode': 'existing',
                },
            }
        return {
            'type': 'ir.actions.act_window',
            'name': _('Dossier'),
            'res_model': 'documents.folder',
            'view_mode': 'form',
            'res_id': folder.id,
            'target': 'current',
        }

    def action_open_dossier_wizard_create(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Crear dossier'),
            'res_model': 'sid.dossier.assign.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_sale_order_id': self.id,
                'default_quotation_id': self.quotations_id.id if self.quotations_id else False,
                'default_contract_kind': 'principal' if (self.quotations_id and not self.quotations_id.parent_id) else 'adenda',
                'default_mode': 'new',
            },
        }

    def action_open_dossier_wizard_link(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Vincular dossier'),
            'res_model': 'sid.dossier.assign.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_sale_order_id': self.id,
                'default_quotation_id': self.quotations_id.id if self.quotations_id else False,
                'default_contract_kind': 'principal' if (self.quotations_id and not self.quotations_id.parent_id) else 'adenda',
                'default_mode': 'existing',
            },
        }
