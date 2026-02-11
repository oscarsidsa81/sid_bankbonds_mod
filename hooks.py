# -*- coding: utf-8 -*-
from odoo import api, SUPERUSER_ID


def post_init_migrate_from_studio(cr, _registry):
    env = api.Environment(cr, SUPERUSER_ID, {})

    # Modelos
    try :
        Old = env["x_bonds.orders"]
        New = env["sid_bonds_orders"]
    except KeyError :
        return

    state_map = {
        "draft": "draft",
        "sent": "sent",
        "pending_bank": "pending_bank",
        "receipt": "receipt",
        "solicit_dev": "solicit_dev",
        "recovered": "recovered",
        "solicit_can": "solicit_can",
        "canceled": "cancelled",  # Studio usa 'canceled', nuevo usa 'cancelled'
    }
    aval_type_map = {
        "prov": "prov",
        "adelanto": "adel",
        "adel" : "adel",
        "fiel": "fiel",
        "gar": "gar",
        "fiel_gar": "fiel_gar",
    }

    # --- utilidades robustas ---

    def _old_get(rec, *names, default=False):
        """Lee campos de Studio/UI de forma tolerante a renombres o inexistencia."""
        for n in names:
            if n and n in rec._fields:
                return rec[n]
        return default

    # --- detectar migraciones previas y corregir registros incompletos ---
    legacy_rows = New.sudo().search_read(
        [("legacy_x_bonds_id", "!=", False)],
        ["id", "legacy_x_bonds_id", "amount", "currency_id"],
    )

    legacy_to_new_id = {r["legacy_x_bonds_id"]: r["id"] for r in legacy_rows if r.get("legacy_x_bonds_id")}
    existing_legacy_ids = set(legacy_to_new_id.keys())

    # Los que ya existen pero vienen mal: amount=0 o currency_id vacío.
    bad_legacy_ids = {
        r["legacy_x_bonds_id"]
        for r in legacy_rows
        if r.get("legacy_x_bonds_id")
        and (
            (r.get("amount") in (0, 0.0, False, None))
            or (not r.get("currency_id"))
        )
    }

    # Olds a crear (no existen en New) + olds a reparar (ya existen, pero incompletos)
    old_recs = Old.sudo().search([
        "|",
        ("id", "not in", list(existing_legacy_ids)),
        ("id", "in", list(bad_legacy_ids)),
    ])
    if not old_recs:
        return

    legacy_to_new = {}  # ids creados en este post_init
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
        x_name = _old_get(o, "x_name", default=False)
        x_cliente = _old_get(o, "x_cliente", default=False)
        x_banco = _old_get(o, "x_banco", default=False)
        x_currency_id = _old_get(o, "x_currency_id", default=False)
        x_importe = _old_get ( o, "x_importe", default= 0.0 ) or 0.0
        x_create = _old_get(o, "x_create", default=False)
        x_date = _old_get(o, "x_date", default=False)
        x_modo = _old_get(o, "x_modo", default=False)
        x_revisado = _old_get(o, "x_revisado", default=False)
        x_estado = _old_get(o, "x_estado", default=False)
        x_tipo = _old_get(o, "x_tipo", default=False)
        x_aval = _old_get(o, "x_aval", default=False)
        x_pedidos = _old_get(o, "x_pedidos", default=False)

        # Si ya existe en New pero está incompleto, lo reparamos (sin recrear)
        if o.id in bad_legacy_ids and o.id in legacy_to_new_id:
            new_rec = New.sudo().browse(legacy_to_new_id[o.id])
            upd = {}

            # amount: si está a 0 y el legacy trae valor, lo copiamos
            if (new_rec.amount in (0, 0.0, False, None)) and x_importe not in (False, None):
                upd["amount"] = float(x_importe or 0.0)

            # currency_id: si está vacío, prioriza legacy; si no hay, usa moneda compañía
            if not new_rec.currency_id:
                if x_currency_id:
                    upd["currency_id"] = x_currency_id.id
                else:
                    upd["currency_id"] = env.company.currency_id.id

            # Campos básicos: en reparaciones también rellenamos si vienen vacíos
            if not new_rec.reference and x_name:
                upd["reference"] = x_name
            if not new_rec.name and x_name:
                upd["name"] = x_name

            if upd:
                new_rec.write(upd)
            continue

        # Si no existe, lo creamos
        vals = {
            "legacy_x_bonds_id": o.id,
            "reference": x_name or False,
            "name": x_name or False,
            "partner_id": x_cliente.id if x_cliente else False,
            "journal_id": x_banco.id if x_banco else False,
            "currency_id": x_currency_id.id or False,
            "amount": float(x_importe or 0.0),
            "issue_date": x_create or False,
            "due_date": x_date or False,
            "is_digital": bool(x_modo),
            "reviewed": bool(x_revisado),
            "state": state_map.get(x_estado) or "draft",
            "aval_type": aval_type_map.get(x_tipo) or False,
            "pdf_aval": x_aval or False,
            "contract_ids": [(6, 0, x_pedidos.ids)] if x_pedidos else [(6, 0, [])],
        }

        batch.append(vals)
        batch_old_ids.append(o.id)

        if len(batch) >= 200:
            _flush_batch()

    _flush_batch()

    # Si sólo hemos reparado (sin crear), no hace falta re-enlazar nada.
    if not legacy_to_new:
        return

    old_ids = list(legacy_to_new.keys())

    # --- Re-enlazar chatter/actividades/adjuntos ---
    msgs = env["mail.message"].sudo().search([
        ("model", "=", "x_bonds.orders"),
        ("res_id", "in", old_ids),
    ])
    for m in msgs:
        new_id = legacy_to_new.get(m.res_id)
        if new_id:
            m.write({"model": "sid_bonds_orders", "res_id": new_id})

    followers = env["mail.followers"].sudo().search([
        ("res_model", "=", "x_bonds.orders"),
        ("res_id", "in", old_ids),
    ])
    for f in followers:
        new_id = legacy_to_new.get(f.res_id)
        if new_id:
            f.write({"res_model": "sid_bonds_orders", "res_id": new_id})

    acts = env["mail.activity"].sudo().search([
        ("res_model", "=", "x_bonds.orders"),
        ("res_id", "in", old_ids),
    ])
    for a in acts:
        new_id = legacy_to_new.get(a.res_id)
        if new_id:
            a.write({"res_model": "sid_bonds_orders", "res_id": new_id})

    atts = env["ir.attachment"].sudo().search([
        ("res_model", "=", "x_bonds.orders"),
        ("res_id", "in", old_ids),
    ])
    for att in atts:
        new_id = legacy_to_new.get(att.res_id)
        if not new_id:
            continue
        vals = {"res_model": "sid_bonds_orders", "res_id": new_id}
        if att.res_field == "x_aval":
            vals["res_field"] = "pdf_aval"
        att.write(vals)
