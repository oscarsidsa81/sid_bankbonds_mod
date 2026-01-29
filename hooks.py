#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


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

    def _old_get(rec, *names, default=False):
        """Lee campos de Studio/UI de forma tolerante.

        En algunas BBDD el usuario puede haber renombrado un campo Studio, o puede
        no existir. Con esto evitamos AttributeError en el hook.
        """
        for n in names:
            if n and n in rec._fields:
                return rec[n]
        return default

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
        # En Studio/UI, algunos campos pueden haber cambiado de nombre o no existir en todas las BBDD.
        # Usamos _old_get para que la migración sea tolerante a variantes.
        x_name = _old_get(o, "x_name", default=False)
        x_cliente = _old_get(o, "x_cliente", default=False)
        x_banco = _old_get(o, "x_banco", default=False)
        x_currency = _old_get(o, "x_currency_id", "x_currency", default=False)
        # Se han visto variantes: x_importe / x_importe (monetary)
        x_importe = _old_get(o, "x_importe", "x_importe", default=0.0) or 0.0
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

            # Referencia
            "reference": x_name or False,
            "name": x_name or False,

            # M2O
            "partner_id": x_cliente.id if x_cliente else False,
            "journal_id": x_banco.id if x_banco else False,
            "currency_id": x_currency.id if x_currency else False,

            # Importes/fechas
            "amount": x_importe,
            "issue_date": x_create or False,
            "due_date": x_date or False,

            # booleanos
            "is_digital": bool(x_modo),
            "reviewed": bool(x_revisado),

            # selección
            "state": state_map.get(x_estado) or "draft",
            "aval_type": aval_type_map.get(x_tipo) or False,

            # binario (si está en attachment, Odoo mantendrá el ir.attachment)
            "pdf_aval": x_aval or False,

            # M2M contratos/pedidos
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

    # 5) Documents: mover documentos (documents.document) vinculados al modelo antiguo
    # al folder "AVALES" y reengancharlos al modelo nuevo.
    _migrate_documents_to_avales(env, legacy_to_new)

    # 6) Reglas de acceso: evitar depender de xmlids de otros módulos
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


def _migrate_documents_to_avales(env, legacy_to_new):
    """Migrate Documents app entries related to legacy bonds.

    This handles:
      - documents.document.folder_id -> "AVALES"
      - ir.attachment.res_model/res_id -> sid_bonds_orders/new_id
      - (optional) cloud_base: ir.attachment.clouds_folder_id set to the workspace of the folder
        without rewriting res_model/res_id (context no_folder_update=True).
    """

    # Documents module may not be installed
    if "documents.document" not in env:
        return

    Docs = env["documents.document"].sudo()
    Att = env["ir.attachment"].sudo()

    # Folder AVALES
    folder = None
    if "documents.folder" in env:
        Folder = env["documents.folder"].sudo()
        folder = Folder.search([("name", "=", "AVALES")], limit=1)
        if not folder:
            root = Folder.search([("parent_folder_id", "=", False)], limit=1)
            vals = {"name": "AVALES"}
            if root:
                vals["parent_folder_id"] = root.id
            folder = Folder.create(vals)

    # cloud_base workspace folder (optional)
    clouds_folder_id = False
    if folder and "clouds.folder" in env:
        cfolder = env["clouds.folder"].sudo().search([
            ("res_model", "=", "documents.folder"),
            ("res_id", "=", folder.id),
        ], limit=1)
        if cfolder:
            clouds_folder_id = cfolder.id

    # Find documents whose attachment points to legacy model
    docs = Docs.search([
        ("attachment_id.res_model", "=", "x_bonds.orders"),
        ("attachment_id.res_id", "in", list(legacy_to_new.keys())),
    ])

    if not docs:
        return

    for doc in docs:
        att = doc.attachment_id
        if not att:
            continue
        new_id = legacy_to_new.get(att.res_id)
        if not new_id:
            continue

        # 1) Move to AVALES folder (Documents UI)
        if folder and getattr(doc, "folder_id", False):
            try:
                doc.write({"folder_id": folder.id})
            except Exception:
                _logger.exception("sid_bankbonds_mod: cannot move document %s to folder AVALES", doc.id)

        # 2) Ensure attachment points to new bond record
        vals = {"res_model": "sid_bonds_orders", "res_id": new_id}
        # Preserve field binding if it was Studio pdf
        if att.res_field == "x_aval":
            vals["res_field"] = "pdf_aval"

        # If cloud module is present, optionally pin the cloud folder (without altering res_model/res_id)
        if clouds_folder_id and hasattr(att, "clouds_folder_id"):
            vals_cloud = dict(vals)
            vals_cloud["clouds_folder_id"] = clouds_folder_id
            att.with_context(no_folder_update=True).write(vals_cloud)
        else:
            att.write(vals)

