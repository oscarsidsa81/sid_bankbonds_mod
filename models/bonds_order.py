# -*- coding: utf-8 -*-
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

class BondsOrder ( models.Model ) :
    _name = "sid_bonds_orders"
    _description = "Avales"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc"

    _BOND_STATES_SKIP_NOTIFY = {"expired", "solicit_dev", "recovered",
                                "solicit_can", "cancelled"}

    name = fields.Char (
        string="Referencia",
        default=lambda self : _ ( "New" ),
        copy=False,
        store=True,
        tracking=True,
    )
    reference = fields.Char ( string="Referencia (externa)" )

    partner_id = fields.Many2one ( "res.partner", string="Cliente",
                                   tracking=True, store=True )
    journal_id = fields.Many2one ( "account.journal", string="Banco",
                                   store=True )
    currency_id = fields.Many2one (
        "res.currency",
        string="Moneda",
        default=lambda self : self.env.company.currency_id.id,
        store=True,
        tracking=True,
    )
    amount = fields.Monetary ( string="Importe", currency_field="currency_id",
                               store=True, tracking=True )

    issue_date = fields.Date ( string="Fecha Emisión", store=True,
                               tracking=True )
    due_date = fields.Date ( string="Fecha vencimiento", store=True,
                             tracking=True )
    is_digital = fields.Boolean ( string="Digital", store=True, tracking=True )
    reviewed = fields.Boolean ( string="Revisado", store=True, tracking=True )

    origin_document = fields.Char (
        string="Documento de Origen",
        compute="_compute_documento_origen",
        store=True,
    )

    contract_ids = fields.Many2many (
        "sale.quotations",
        relation="sid_bonds_quotation_rel",
        column1="bond_id",
        column2="quotation_id",
        string="Contratos / Pedidos",
        tracking=True,
        copy=False,
    )

    base_pedidos = fields.Monetary (
        string="Base Imponible Pedidos",
        currency_field="currency_id",
        compute="_compute_base_pedidos",
        store=True,
        # No lo hagas editable en vistas, pero permitimos write interno para tracking/avisos.
        readonly=False,
        copy=True,
        tracking=True,
    )

    pdf_aval = fields.Binary ( string="PDF Aval", attachment=True, store=True )

    variation_threshold_pct = fields.Float(
        string="Umbral de variación (%)",
        default=3.0,
        tracking=True,
        help="Porcentaje mínimo de variación en Base Imponible Pedidos para publicar aviso y crear actividad.",
    )

    legacy_x_bonds_id = fields.Integer(
        string="Legacy x_bonds.orders ID",
        index=True,
        readonly=True,
        copy=False,
        help="ID del registro origen (modelo Studio x_bonds.orders), para migración idempotente.",
    )

    state = fields.Selection (
        [
            ("draft", "Borrador"),
            ("pending_bank", "Pendiente Banco"),
            ("requested", "Solicitado"),
            ("sent", "Enviado a cliente"),
            ("receipt", "Recibido cliente"),
            ("active", "Vigente"),
            ("expired", "Vencido"),
            ("solicit_dev", "Solicitada Devolución"),
            ("recovered", "Recuperado"),
            ("solicit_can", "Solicitada Cancelación"),
            ("cancelled", "Cancelado"),
        ],
        string="Estado",
        default="draft",
        store=True,
        tracking=True,
    )

    state_manage = fields.Selection(
        [
            ("new", "Nuevos"),
            ("current", "Vigentes"),
            ("finished", "Vencido"),
            ("done", "Finalizado"),
        ],
        string="Gestión",
        compute="_compute_state_manage",
        store=True,
        tracking=True,
        readonly=True,
    )

    aval_type = fields.Selection (
        [
            ("prov", "Provisional"),
            ("adel", "Adelanto"),
            ("fiel", "Fiel Cumplimiento"),
            ("gar", "Garantía"),
            ("fiel_gar", "Fiel Cumplimiento y Garantía"),
        ],
        string="Tipo",
        tracking=True,
    )

    description = fields.Text ( string="Descripción / Notas" )

    @api.depends("state")
    def _compute_state_manage(self):
        map_new = {"draft", "pending_bank", "requested", "sent"}
        map_current = {"receipt", "active"}
        map_finished = {"expired", "solicit_dev", "recovered", "solicit_can"}
        map_done = {"cancelled"}

        for bond in self:
            st = bond.state
            if st in map_new:
                bond.state_manage = "new"
            elif st in map_current:
                bond.state_manage = "current"
            elif st in map_finished:
                bond.state_manage = "finished"
            elif st in map_done:
                bond.state_manage = "done"
            else:
                # fallback defensivo (por si se añade un estado nuevo en el futuro)
                bond.state_manage = "new"

    def write(self, vals) :
        # 1) Guardamos el valor anterior (calculado) antes del write
        # OJO: base_pedidos es compute store=False => se calcula al acceder
        old_map = {b.id : b.base_pedidos for b in self}

        # 2) write normal (y lógica de name/reference)
        if "reference" in vals and vals.get ( "reference" ) :
            vals = dict ( vals )
            vals["name"] = vals["reference"]

        res = super ().write ( vals )

        # 3) Si el write afecta a algo que pueda cambiar la base, evaluamos después
        # Esto evita spam si editas campos no relacionados.
        triggers = {"contract_ids", "base_pedidos",
                    "partner_id"}  # si quieres, añade aquí otras cosas
        if triggers.intersection ( vals.keys () ) :
            self._post_base_pedidos_variation_note ( old_map )

        return res

    def _schedule_creator_todo(self, old_value, new_value, pct) :
        """
        Activity tipo 'Por hacer' para create_uid (si existe).
        Evita duplicados abiertos con el mismo resumen.
        """
        self.ensure_one ()
        if not self.create_uid :
            return

        # tipo de actividad 'Por hacer' estándar
        todo_type = self.env.ref ( "mail.mail_activity_data_todo",
                                   raise_if_not_found=False )
        if not todo_type :
            return

        # Umbral por aval (default 3.0 si vacío)
        thr = float ( getattr ( self, "variation_threshold_pct", 3.0 ) or 0.0 )

        summary = _ ( "Revisar necesidad de ampliar aval" )

        note = _ (
            "Se detectó variación >= %(thr).2f%% en Base Imponible Pedidos.\n"
            "Anterior: %(old).2f\n"
            "Nuevo: %(new).2f\n"
            "Cambio: %(pct).2f%%\n\n"
            "Revisar si es necesario ampliar el aval o avales asociados."
        ) % {
                   "thr" : thr,
                   "old" : old_value,
                   "new" : new_value,
                   "pct" : pct,
               }

        # Evita spam: NO buscar por mail.activity.state (no es stored en Odoo 15)
        existing = self.env["mail.activity"].search ( [
            ("res_model", "=", self._name),
            ("res_id", "=", self.id),
            ("user_id", "=", self.create_uid.id),
            ("activity_type_id", "=", todo_type.id),
            ("summary", "=", summary),
            ("date_done", "=", False),
        ], limit=1 )
        if existing :
            return

        deadline = fields.Date.context_today ( self )  # hoy
        self.activity_schedule (
            activity_type_id=todo_type.id,
            user_id=self.create_uid.id,
            summary=summary,
            note=note,
            date_deadline=deadline,
        )

    def _get_bonds_manager_partners(self) :
        """Devuelve res.partner (partners) de usuarios del grupo de Gestión de Avales."""
        group = self.env.ref (
            "sid_bankbonds_mod.group_bonds_manager",
            raise_if_not_found=False )
        if not group :
            return self.env["res.partner"]
        users = group.users
        return users.mapped ( "partner_id" )

    def _post_base_pedidos_variation_note(self, old_map) :
        """
        old_map: {bond_id: old_base_pedidos}
        Si variación > umbral y estado permitido:
          - publica nota interna mencionando a usuarios del grupo (si hay)
          - crea activity tipo Por hacer para create_uid
        """
        partners = self._get_bonds_manager_partners ()

        for bond in self :
            # 1) estados excluidos
            if bond.state in self._BOND_STATES_SKIP_NOTIFY :
                continue

            old = float ( old_map.get ( bond.id, 0.0 ) or 0.0 )
            new = float ( bond.base_pedidos or 0.0 )

            # si ambos 0, nada
            if old == 0.0 and new == 0.0 :
                continue

            threshold = float ( bond.variation_threshold_pct or 3.0 )

            # 2) % contra valor anterior (si old == 0, no se puede dividir)
            if old == 0.0 :
                pct = 100.0
                changed = (new != 0.0)
            else :
                pct = abs ( new - old ) / abs ( old ) * 100.0
                changed = pct > threshold

            if not changed :
                continue

            # 3) menciones HTML (solo si hay partners)
            mentions_html = ""
            if partners :
                mentions_html = " ".join (
                    f'<a data-oe-model="res.partner" data-oe-id="{p.id}">@{p.display_name}</a>'
                    for p in partners
                )

            body = _ (
                "<p><b>Variación en Base Imponible Pedidos</b> (&gt; %(thr).2f%%)</p>"
                "<p>Anterior: %(old)s<br/>Nuevo: %(new)s<br/>Cambio: %(pct).2f%%</p>"
                "%(mentions)s"
            ) % {
                       "old" : old,
                       "new" : new,
                       "pct" : pct,
                       "thr" : threshold,
                       "mentions" : f"<p>{mentions_html}</p>" if mentions_html else "",
                   }

            # 4) Si hay partners, notificar; si no, postear nota sin notify (evita warning)
            bond.message_post (
                body=body,
                message_type="comment",
                subtype_xmlid="mail.mt_note",
            )

            # 4b) Notificación solo si hay destinatarios
            if partners :
                bond.message_notify (
                    body=body,
                    message_type="comment",
                    subtype_xmlid="mail.mt_note",
                    partner_ids=partners.ids,
                )

            # 5) Activity al creador
            bond._schedule_creator_todo ( old, new, pct )

    def action_view_sale_orders(self) :
        bonds = self.filtered ( lambda b : b.contract_ids )
        action = self.env.ref ( "sale.action_orders" ).read ()[0]
        if not bonds :
            return action

        quotation_ids = bonds.mapped ( "contract_ids" ).ids
        action["domain"] = [
            ("quotations_id", "in", quotation_ids),
            ("state", "=", "sale"),
        ]
        action["context"] = dict ( self.env.context )
        return action

    # Con esta computación podemos tener el amount_untaxed de los pedidos confirmados que estén relacionados con el valor de quotations_id
    @api.depends (
        "contract_ids",
        "partner_id",
        "contract_ids.sale_order_ids.amount_untaxed",
        "contract_ids.sale_order_ids.state",
        "contract_ids.sale_order_ids.partner_id",
    )
    def _compute_base_pedidos(self) :
        for bond in self :
            if not bond.contract_ids or not bond.partner_id :
                # compute store: asignación directa (NO write dentro del compute)
                bond.base_pedidos = 0.0
                continue

            orders = bond.contract_ids.mapped ( "sale_order_ids" ).filtered (
                lambda
                    so : so.partner_id.id == bond.partner_id.id and so.state == "sale"
            )
            bond.base_pedidos = sum ( orders.mapped ( "amount_untaxed" ) )

    @api.depends ( "contract_ids", "partner_id" )
    def _compute_documento_origen(self) :
        for record in self :
            if record.contract_ids and record.partner_id :
                sale_orders = self.env["sale.order"].search ( [
                    ("quotations_id", "in", record.contract_ids.ids),
                    ("partner_id", "=", record.partner_id.id),
                    ("state", "=", "sale"),
                ] )
                record.origin_document = ", ".join (
                    sale_orders.mapped ( "name" ) )
            else :
                record.origin_document = False

    def action_request(self) :
        for rec in self :
            if rec.state != "draft" :
                raise UserError (
                    _ ( "Solo puedes solicitar desde Borrador." ) )
            rec.state = "requested"

    def action_activate(self) :
        for rec in self :
            if rec.state not in ("requested", "draft") :
                raise UserError (
                    _ ( "Solo puedes poner Vigente desde Solicitado o Borrador." ) )
            if not rec.amount or rec.amount <= 0 :
                raise UserError ( _ ( "El importe debe ser positivo." ) )
            rec.state = "active"

    def action_expire(self) :
        for rec in self :
            if rec.state != "active" :
                raise UserError ( _ ( "Solo puedes vencer un aval vigente." ) )
            rec.state = "expired"

    def action_cancel(self) :
        for rec in self :
            if rec.state in ("expired", "cancelled") :
                continue
            rec.state = "cancelled"

    def action_set_draft(self) :
        for rec in self :
            rec.state = "draft"

    @api.model_create_multi
    def create(self, vals_list) :
        records = super ().create ( vals_list )
        for rec in records :
            if rec.name == _ ( "New" ) :
                rec.name = self.env["ir.sequence"].next_by_code (
                    "sid_bonds_orders" ) or _ ( "New" )
        return records

    def unlink(self) :
        for rec in self :
            if rec.state in ("active", "expired") :
                raise UserError (
                    _ ( "No puedes eliminar avales vigentes o vencidos." ) )
        return super ().unlink ()




class SaleQuotationsBonds(models.Model):
    _name = "sale.quotations"
    _inherit = ["sale.quotations", "mail.thread", "mail.activity.mixin"]
    _parent_store = True  # activa parent_path (solo si tienes parent_path en el modelo)
    _parent_name = "parent_id"

    parent_id = fields.Many2one (
        comodel_name="sale.quotations",
        string="Contrato Principal",
        index=True,
        ondelete="restrict",
    )

    child_ids = fields.One2many (
        comodel_name="sale.quotations",
        inverse_name="parent_id",
        string="Adendas",
    )

    parent_path = fields.Char(index=True)

    partner_id = fields.Many2one (
        "res.partner",
        string="Cliente",
        compute="_compute_sale_partner_id",
        tracking=True,
        store=True )

    # # varios avales para un solo contrato o varios
    bond_ids = fields.Many2many (
        comodel_name="sid_bonds_orders",
        relation="sid_bonds_quotation_rel",
        column1="quotation_id",
        column2="bond_id",
        string="Avales",
    )

    # Relación "ancla" (debe existir realmente en tu modelo)
    sale_order_ids = fields.One2many (
        comodel_name="sale.order",
        inverse_name="quotations_id",
        string="Pedidos (Sale Orders)",
        readonly=True,
    )

    # Campo para mostrar SOLO los confirmados (state='sale')
    sale_order_sale_ids = fields.Many2many (
        comodel_name="sale.order",
        string="Pedidos confirmados",
        compute="_compute_sale_order_sale_ids",
        store=False,
        readonly=True,
    )

    @api.constrains("parent_id", "child_ids")
    def _check_parent_child_exclusive(self):
        for rec in self:
            if rec.parent_id and rec.child_ids:
                raise ValidationError(
                    _("Un contrato no puede tener 'Principal' y 'Adendas' a la vez.")
                )

    @api.depends (
        "parent_id",
        "child_ids",
        "parent_path",
        "sale_order_ids.state",
        "child_ids.sale_order_ids.state",
        "parent_id.sale_order_ids.state",
    )
    def _compute_sale_order_sale_ids(self) :
        for rec in self :
            family = rec._get_family_quotations ()
            orders = family.mapped ( "sale_order_ids" ).filtered (
                lambda so : so.state == "sale" )
            rec.sale_order_sale_ids = orders

    @api.depends(
        "sale_order_sale_ids",
        "sale_order_sale_ids.partner_id",
        "sale_order_sale_ids.date_order",
    )
    def _compute_sale_partner_id(self) :
        """
        Compute store=True SIN efectos colaterales:
        - No message_post / message_notify dentro de compute (evita spam y lentitud en install/recompute masivo).
        - Resuelve partner por el pedido confirmado más reciente.
        - Si hay varios partners, solo lo registra en log (y además se salta en install_mode).
        """
        for rec in self :
            orders = rec.sale_order_sale_ids.filtered (
                lambda so : so.partner_id )

            if not orders :
                rec.partner_id = False
                continue

            # más reciente por date_order (fallback viejo si está vacío)
            def _key(so) :
                return so.date_order or fields.Datetime.from_string (
                    "1970-01-01 00:00:00" )

            so_latest = orders.sorted ( key=_key, reverse=True )[:1]
            rec.partner_id = so_latest.partner_id if so_latest else False

            # Si hay más de un cliente, NO postear en chatter desde compute.
            # En instalación, ni siquiera loguear (evita ruido).
            partners = orders.mapped ( "partner_id" )
            if len ( partners ) > 1 and not rec.env.context.get (
                    "install_mode" ) :
                _logger.warning (
                    "sale.quotations %s: múltiples clientes en pedidos confirmados (%s). "
                    "Se fija el del pedido más reciente: %s",
                    rec.display_name,
                    ", ".join ( partners.mapped ( "display_name" ) ),
                    rec.partner_id.display_name if rec.partner_id else "N/A",
                )

    # --- Smart button counters ---
    child_count = fields.Integer(string="Nº Adendas", compute="_compute_smart_counts")
    sale_order_count = fields.Integer(string="Nº Pedidos", compute="_compute_smart_counts")
    bond_count = fields.Integer(string="Nº Avales", compute="_compute_smart_counts")
    purchase_count = fields.Integer(string="Nº Compras", compute="_compute_smart_counts")

    @api.depends("child_ids", "sale_order_sale_ids", "bond_ids")
    def _compute_smart_counts(self):
        for rec in self:
            rec.child_count = len(rec.child_ids)
            rec.sale_order_count = len(rec.sale_order_sale_ids)
            rec.bond_count = len(rec.bond_ids)
            rec.purchase_count = rec._get_purchase_orders().sudo().search_count(
                rec._get_purchase_domain()
            )

    # --- Helpers for purchases ---
    def _get_procurement_groups(self):
        """Return procurement groups from linked sale orders."""
        self.ensure_one()
        sale_orders = self.sale_order_sale_ids

        # Depending on Odoo version/custom, sale order can use group_id or procurement_group_id
        groups = sale_orders.mapped("procurement_group_id")
        return groups.filtered(lambda g: g)

    def _get_purchase_domain(self):
        """Domain for purchase orders linked to the procurement groups of linked sale orders."""
        self.ensure_one()
        groups = self._get_procurement_groups()
        if not groups:
            return [("id", "=", 0)]
        # purchase.order usually has group_id
        return [("group_id", "in", groups.ids)]

    def _get_purchase_orders(self):
        return self.env["purchase.order"]

    # --- Smart button actions ---
    def action_view_children(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Adendas",
            "res_model": "sale.quotations",
            "view_mode": "tree,form",
            "domain": [("id", "in", self.child_ids.ids)],
            "context": {"default_parent_id": self.id},
        }

    def action_view_sale_orders(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Sale Orders",
            "res_model": "sale.order",
            "view_mode": "tree,form",
            "domain": [("id", "in", self.sale_order_sale_ids.ids)],
            "context": {},
        }

    def action_view_bonds(self):
        self.ensure_one()
        # Ajusta el modelo si no es "bond.bond"
        bond_model = self.bond_ids._name or "bond.bond"
        return {
            "type": "ir.actions.act_window",
            "name": "Avales",
            "res_model": bond_model,
            "view_mode": "tree,form",
            "domain": [("id", "in", self.bond_ids.ids)],
            "context": {},
        }

    def action_view_purchases(self):
        self.ensure_one()
        domain = self._get_purchase_domain()
        return {
            "type": "ir.actions.act_window",
            "name": "Compras",
            "res_model": "purchase.order",
            "view_mode": "tree,form",
            "domain": domain,
            "context": {},
        }

    def _get_effective_partner_from_sale_orders(self):
        """Devuelve el partner del pedido confirmado más reciente (state='sale')."""
        self.ensure_one()
        so = self.sale_order_ids.filtered(lambda s: s.state == "sale")
        if not so:
            return self.env["res.partner"]  # vacío
        so_latest = so.sorted(lambda s: s.date_order or fields.Datetime.now(), reverse=True)[:1]
        return so_latest.partner_id

    def _get_family_quotations(self) :
        """Devuelve root + descendientes. Soporta registros nuevos (NewId) en onchange."""
        self.ensure_one ()

        # 1) si soy adenda, el root es mi parent (si existe), si no, yo
        root = self.parent_id or self

        # 2) Si el root aún no está guardado, NO se puede usar child_of en SQL
        if not root.id or isinstance ( root.id, models.NewId ) :
            # En onchange solo podemos devolver lo que "vemos" en memoria
            # - yo mismo
            # - mis child_ids (si yo soy root)
            # - o los siblings si soy child y el parent tiene child_ids en memoria
            if self.parent_id :
                # soy adenda: familia = parent + siblings + yo (lo que haya cargado en pantalla)
                fam = self.parent_id | self.parent_id.child_ids
                return fam
            else :
                # soy principal nuevo: familia = yo + mis child_ids (en memoria)
                return self | self.child_ids

        # 3) Caso normal (guardado): SQL con child_of (rápido y completo)
        return self.search ( [("id", "child_of", root.id)] )

    @api.constrains("parent_id", "child_ids")
    def _check_parent_child_same_partner(self):
        for rec in self:
            rec_partner = rec._get_effective_partner_from_sale_orders()

            # --- Regla 1: si es adenda (tiene parent), el parent debe tener mismo cliente ---
            if rec.parent_id:
                parent_partner = rec.parent_id._get_effective_partner_from_sale_orders()

                # Si ambos tienen partner “resuelto” y no coincide -> bloquear
                if rec_partner and parent_partner and rec_partner.id != parent_partner.id:
                    raise ValidationError(_(
                        "No puedes vincular esta adenda a un contrato principal con cliente distinto.\n\n"
                        "Cliente (adenda): %(c1)s\nCliente (principal): %(c2)s"
                    ) % {
                        "c1": rec_partner.display_name,
                        "c2": parent_partner.display_name,
                    })

            # --- Regla 2: si es principal (tiene children), todos deben tener mismo cliente ---
            if rec.child_ids:
                for child in rec.child_ids:
                    child_partner = child._get_effective_partner_from_sale_orders()
                    if rec_partner and child_partner and rec_partner.id != child_partner.id:
                        raise ValidationError(_(
                            "No puedes añadir una adenda con cliente distinto al del contrato principal.\n\n"
                            "Cliente (principal): %(c1)s\nCliente (adenda): %(c2)s\nAdenda: %(child)s"
                        ) % {
                            "c1": rec_partner.display_name,
                            "c2": child_partner.display_name,
                            "child": child.display_name,
                        })

            # --- (Opcional) Modelo estricto a 2 niveles ---
            # Si quieres prohibir “adenda con hijos”:
            if rec.parent_id and rec.child_ids:
                raise ValidationError(_(
                    "Una adenda no puede tener a su vez adendas. "
                    "Quita el contrato principal o las adendas antes de continuar."
                ))


