# -*- coding: utf-8 -*-

from odoo import api, SUPERUSER_ID


def post_init_migrate_from_studio(cr, registry):
    """Migración x_bonds.orders (Studio/UI) -> sid_bonds_orders (módulo nuevo).

    Se ejecuta al instalar el módulo nuevo.

    Reglas principales:
    - Es idempotente (no duplica): usa sid_bonds_orders.legacy_x_bonds_id.
    - Copia campos básicos, binarios y relaciones a sale.quotations.
    - Reubica chatter y adjuntos (mail.message, mail.followers, mail.activity, ir.attachment)
      para no perder histórico.

    Si el modelo antiguo no existe, no hace nada.
    """

    env = api.Environment(cr, SUPERUSER_ID, {})

    # Modelo antiguo (Studio) puede no existir en todas las BD
    try:
        Old = env["x_bonds.orders"]
    except KeyError:
        return

    New = env["sid_bonds_orders"]

    # --- Mapeos de selección ---
    state_map = {
        "draft": "draft",
        "pending_bank": "pending_bank",
        "sent": "sent",
        "receipt": "receipt",
        "solicit_dev": "solicit_dev",
        "recovered": "recovered",
        "solicit_can": "solicit_can",
        "canceled": "cancelled",  # Studio usa 'canceled', nuevo usa 'cancelled'
    }
    aval_type_map = {
        "adelanto": "adel",  # Studio -> nuevo
        "fiel": "fiel",
        "gar": "gar",
        "fiel_gar": "fiel_gar",
    }

    # Solo migramos los que no estén ya migrados
    legacy_rows = New.sudo().search_read(
        [("legacy_x_bonds_id", "!=", False)], ["legacy_x_bonds_id"]
    )
    existing_legacy_ids = {r["legacy_x_bonds_id"] for r in legacy_rows if r.get("legacy_x_bonds_id")}

    old_recs = Old.sudo().search([("id", "not in", list(existing_legacy_ids))])
    if not old_recs:
        return

    legacy_to_new = {}

    # Creamos en lotes (evita consumo excesivo de memoria)
    batch = []
    batch_old_ids = []

    def _flush_batch():
        nonlocal batch, batch_old_ids, legacy_to_new
        if not batch:
            return

        new_recs = New.sudo().create(batch)
        for o_id, n in zip(batch_old_ids, new_recs):
            legacy_to_new[o_id] = n.id

        batch = []
        batch_old_ids = []

    for o in old_recs:
        vals = {
            "legacy_x_bonds_id": o.id,

            # Referencia
            "reference": o.x_name or False,
            "name": o.x_name or False,

            # M2O
            "partner_id": o.x_cliente.id if o.x_cliente else False,
            "journal_id": o.x_banco.id if o.x_banco else False,
            "currency_id": o.x_currency_id.id if o.x_currency_id else False,

            # Importes/fechas
            "amount": o.x_importe or 0.0,
            "issue_date": o.x_create or False,
            "due_date": o.x_date or False,

            # booleanos
            "is_digital": bool(o.x_modo),
            "reviewed": bool(o.x_revisado),

            # selección
            "state": state_map.get(o.x_estado) or "draft",
            "aval_type": aval_type_map.get(o.x_tipo) or False,

            # binario (si está en attachment, Odoo mantendrá el ir.attachment)
            "pdf_aval": o.x_aval or False,

            # M2M contratos/pedidos
            "contract_ids": [(6, 0, o.x_pedidos.ids)] if getattr(o, "x_pedidos", False) else [(6, 0, [])],
        }

        batch.append(vals)
        batch_old_ids.append(o.id)
        if len(batch) >= 200:
            _flush_batch()

    _flush_batch()

    if not legacy_to_new:
        return

    old_ids = list(legacy_to_new.keys())

    # --- Re-enlazar chatter/actividades/adjuntos ---
    # 1) Mensajes
    msgs = env["mail.message"].sudo().search([
        ("model", "=", "x_bonds.orders"),
        ("res_id", "in", old_ids),
    ])
    for m in msgs:
        new_id = legacy_to_new.get(m.res_id)
        if new_id:
            m.write({"model": "sid_bonds_orders", "res_id": new_id})

    # 2) Seguidores
    followers = env["mail.followers"].sudo().search([
        ("res_model", "=", "x_bonds.orders"),
        ("res_id", "in", old_ids),
    ])
    for f in followers:
        new_id = legacy_to_new.get(f.res_id)
        if new_id:
            f.write({"res_model": "sid_bonds_orders", "res_id": new_id})

    # 3) Actividades
    acts = env["mail.activity"].sudo().search([
        ("res_model", "=", "x_bonds.orders"),
        ("res_id", "in", old_ids),
    ])
    for a in acts:
        new_id = legacy_to_new.get(a.res_id)
        if new_id:
            a.write({"res_model": "sid_bonds_orders", "res_id": new_id})

    # 4) Adjuntos (incluye el de x_aval si Studio lo guardó como attachment)
    atts = env["ir.attachment"].sudo().search([
        ("res_model", "=", "x_bonds.orders"),
        ("res_id", "in", old_ids),
    ])
    for att in atts:
        new_id = legacy_to_new.get(att.res_id)
        if not new_id:
            continue

        vals = {"res_model": "sid_bonds_orders", "res_id": new_id}
        # Si venía del campo Studio x_aval, lo apuntamos al campo nuevo
        if att.res_field == "x_aval":
            vals["res_field"] = "pdf_aval"
        att.write(vals)

    # 5) Reglas de acceso: evitar depender de xmlids de otros módulos
    _ensure_contract_rules(env)


def _ensure_contract_rules(env):
    """Crea/actualiza una regla básica para `sale.quotations`.

    Importante: no usamos `ref('model_sale_quotations')` porque ese xmlid
    pertenece al módulo que definió el modelo (no necesariamente este), y en
    instalaciones reales puede no existir con el mismo namespace.
    """
    IrRule = env["ir.rule"].sudo()

    model = env["ir.model"]._get("sale.quotations")
    if not model:
        _logger.warning("sid_bankbonds_mod: ir.model for sale.quotations not found; skipping rule")
        return

    name = "All Contracts limited"

    rule = IrRule.search([
        ("name", "=", name),
        ("model_id", "=", model.id),
    ], limit=1)

    vals = {
        "name": name,
        "model_id": model.id,
        "domain_force": "[(1,'=',1)]",
        "perm_read": True,
        "perm_write": True,
        "perm_create": True,
        "perm_unlink": False,
    }

    if rule:
        rule.write(vals)
    else:
        IrRule.create(vals)
