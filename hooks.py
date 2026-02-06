# -*- coding: utf-8 -*-
from odoo import api, SUPERUSER_ID


def post_init_migrate_from_studio(cr, registry):
    env = api.Environment(cr, SUPERUSER_ID, {})

    # Modelos
    Old = env.get("x_bonds.orders")  # modelo Studio
    New = env.get("sid_bonds_orders")  # modelo nuevo

    # Si el modelo antiguo no existe, no hacemos nada
    if not Old or not New:
        return

    state_map = {
        "draft": "draft",
        "sent": "sent",
        "sign": "sign",
        "receipt": "receipt",
        "solicit_dev": "solicit_dev",
        "recovered": "recovered",
        "solicit_can": "solicit_can",
        "canceled": "cancelled",  # Studio usa 'canceled', nuevo usa 'cancelled'
        "cancelled": "cancelled",
    }
    aval_type_map = {
        "prov": "prov",
        "adelanto": "adel",
        "adel": "adel",
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

    def _to_float(v, default=0.0):
        """Convierte monetary/float/str a float de forma segura."""
        if v is False or v is None:
            return float(default)
        # monetary/float/int
        if isinstance(v, (int, float)):
            return float(v)
        # a veces puede venir como string
        if isinstance(v, str):
            s = v.strip()
            if not s:
                return float(default)
            # normalizar formatos típicos ES: "1.234,56"
            # - quitar separador miles
            # - convertir coma decimal a punto
            s = s.replace(" ", "")
            if "," in s and "." in s:
                # asumimos: "." miles, "," decimal
                s = s.replace(".", "").replace(",", ".")
            else:
                # si solo hay coma, es decimal
                s = s.replace(",", ".")
            try:
                return float(s)
            except Exception:
                return float(default)

        # Cualquier otro tipo
        try:
            return float(v)
        except Exception:
            return float(default)

    def _detect_amount_field(rec):
        """Fallback: detecta un campo tipo monetary/float cuyo nombre sugiera importe."""
        # candidatos típicos primero
        candidates = [
            "x_importe",
            "x_amount",
            "x_importe_total",
            "x_importe_aval",
            "x_monto",
        ]
        for c in candidates:
            if c in rec._fields:
                return c

        # heurística por nombre + tipo
        for fname, field in rec._fields.items():
            name_l = (fname or "").lower()
            if ("importe" in name_l or "amount" in name_l) and getattr(field, "type", None) in (
                "float",
                "monetary",
            ):
                return fname

        return None

    # --- evitar duplicados: ya migrados ---
    legacy_rows = New.sudo().search_read(
        [("legacy_x_bonds_id", "!=", False)], ["legacy_x_bonds_id"]
    )
    existing_legacy_ids = {
        r["legacy_x_bonds_id"] for r in legacy_rows if r.get("legacy_x_bonds_id")
    }

    old_recs = Old.sudo().search([("id", "not in", list(existing_legacy_ids))])
    if not old_recs:
        return

    legacy_to_new = {}
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
        x_currency = _old_get(o, "x_currency_id", default=False)

        # ---- AMOUNT robusto ----
        amount_field = _detect_amount_field(o)
        x_importe_raw = _old_get(o, amount_field, default=0.0) if amount_field else 0.0
        x_importe = _to_float(x_importe_raw, default=0.0)

        x_create = _old_get(o, "x_create", default=False)
        x_date = _old_get(o, "x_date", default=False)
        x_modo = _old_get(o, "x_modo", default=False)
        x_revisado = _old_get(o, "x_revisado", default=False)
        x_estado = _old_get(o, "x_estado", default=False)
        x_tipo = _old_get(o, "x_tipo", default=False)
        x_aval = _old_get(o, "x_aval", default=False)
        x_pedidos = _old_get(o, "x_pedidos", default=False)

        vals = {
            "legacy_x_bonds_id": o.id,

            "reference": x_name or False,
            "name": x_name or False,

            "partner_id": x_cliente.id if x_cliente else False,
            "journal_id": x_banco.id if x_banco else False,
            "currency_id": x_currency.id if x_currency else False,

            "amount": x_importe,
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
