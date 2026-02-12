# -*- coding: utf-8 -*-
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def post_init_migrate_from_studio(cr, _registry):
    """
    Migración post-init:
      - x_bonds.orders (Studio) -> sid_bonds_orders (módulo)
      - Copia importes y moneda de forma fiable leyendo SQL (evita casos raros de ORM)
      - Re-enlaza chatter/actividades/adjuntos
      - Re-enlaza documents.document al nuevo modelo
      - Asegura carpeta AVALES existente (reutiliza la actual si está) y crea xml_id estable
        sid_bankbonds_mod.folder_avales para poder referenciarla sin depender de __export__.
    """
    env = api.Environment(cr, SUPERUSER_ID, {})

    # Modelos (si Studio no está instalado, no hacemos nada)
    try:
        Old = env["x_bonds.orders"]
        New = env["sid_bonds_orders"]
    except KeyError:
        return

    # ---------------------------------------------------------------------
    # Helpers
    # ---------------------------------------------------------------------
    def _old_get(rec, *names, default=False):
        """Lee campos de Studio/UI de forma tolerante a renombres o inexistencia."""
        for n in names:
            if n and n in rec._fields:
                return rec[n]
        return default

    def _ensure_xmlid(record, xmlid, *, noupdate=True):
        """Asegura que exista un xml_id apuntando a record (lo crea o lo re-apunta)."""
        if not record:
            return False
        module, name = xmlid.split(".", 1)
        imd = env["ir.model.data"].sudo().search(
            [("module", "=", module), ("name", "=", name)], limit=1
        )
        if imd:
            if imd.model != record._name or imd.res_id != record.id:
                # Re-apuntar para que el resto del módulo no dependa de __export__
                imd.write({"model": record._name, "res_id": record.id, "noupdate": bool(noupdate)})
            return xmlid
        env["ir.model.data"].sudo().create(
            {"module": module, "name": name, "model": record._name, "res_id": record.id, "noupdate": bool(noupdate)}
        )
        return xmlid

    def _ensure_avales_folder():
        """
        Reutiliza la carpeta AVALES ya existente (idealmente la id 745 si existe),
        o la crea si no existe. Devuelve recordset documents.folder.
        """
        DF = env["documents.folder"].sudo()

        folder = DF.browse(745).exists()
        if not folder:
            folder = DF.search([("name", "=", "AVALES")], limit=1)

        if not folder:
            parent = DF.search([("parent_folder_id", "=", False), ("name", "ilike", "internal")], limit=1)
            # fallback al folder interno estándar si existe
            if env.ref("documents.documents_internal_folder", raise_if_not_found=False):
                parent = env.ref("documents.documents_internal_folder").sudo()
            vals = {"name": "AVALES", "parent_folder_id": parent.id if parent else False}
            folder = DF.create(vals)
            _logger.info("Created documents.folder AVALES id=%s", folder.id)
        else:
            _logger.info("Reusing documents.folder AVALES id=%s", folder.id)

        # xmlid estable para el módulo
        _ensure_xmlid(folder, "sid_bankbonds_mod.folder_avales", noupdate=True)

        # Si existe regla/registro en sync.model (Cloud Sync) con doc_domain a una id distinta, la alineamos.
        SM = env["sync.model"].sudo() if "sync.model" in env else None
        if SM:
            # en tu entorno la regla usa doc_domain de documents.document en contexto, p.ej. "[['id','=',745]]"
            rules = SM.search([("name", "ilike", "AVALES")])
            for r in rules:
                if hasattr(r, "doc_domain") and r.doc_domain:
                    # si tiene un id fijo distinto, lo sustituimos.
                    if "745" in r.doc_domain and folder.id == 745:
                        continue
                    # patrón simple: [['id', '=', N]]
                    new_dom = "[['id', '=', %s]]" % folder.id
                    if r.doc_domain.strip() != new_dom:
                        r.write({"doc_domain": new_dom})
                        _logger.info("Updated sync.model(%s) doc_domain -> %s", r.id, new_dom)

        return folder

    def _sql_old_amount_currency(old_id):
        """
        Devuelve (importe, currency_id) leyendo SQL directamente:
        evita situaciones donde el ORM devuelve 0/False por causas laterales.
        """
        cr.execute(
            "SELECT x_importe, x_currency_id FROM x_bonds_orders WHERE id = %s",
            (old_id,),
        )
        row = cr.fetchone()
        if not row:
            return 0.0, False
        amount = row[0] or 0.0
        cur_id = row[1] or False
        try:
            amount = float(amount)
        except Exception:
            amount = 0.0
        return amount, cur_id

    # ---------------------------------------------------------------------
    # Carpeta AVALES (reutilizar la actual, evitar duplicados)
    # ---------------------------------------------------------------------
    avales_folder = False
    if "documents.folder" in env:
        avales_folder = _ensure_avales_folder()

    # ---------------------------------------------------------------------
    # Mapas
    # ---------------------------------------------------------------------
    state_map = {
        "draft": "draft",
        "sent": "sent",
        "pending_bank": "pending_bank",
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

    # ---------------------------------------------------------------------
    # Detectar migraciones previas e identificar registros a reparar
    # ---------------------------------------------------------------------
    legacy_rows = New.sudo().search_read(
        [("legacy_x_bonds_id", "!=", False)],
        ["id", "legacy_x_bonds_id", "amount", "currency_id"],
    )

    legacy_to_new_id = {r["legacy_x_bonds_id"]: r["id"] for r in legacy_rows if r.get("legacy_x_bonds_id")}
    existing_legacy_ids = set(legacy_to_new_id.keys())

    # A reparar si amount=0/False o currency vacío.
    bad_legacy_ids = {
        r["legacy_x_bonds_id"]
        for r in legacy_rows
        if r.get("legacy_x_bonds_id")
        and ((r.get("amount") in (0, 0.0, False, None)) or (not r.get("currency_id")))
    }

    # Olds a crear + olds a reparar
    old_recs = Old.sudo().search([
        "|",
        ("id", "not in", list(existing_legacy_ids)),
        ("id", "in", list(bad_legacy_ids)),
    ])
    if not old_recs:
        _logger.info("No old records to migrate/repair.")
        return

    _logger.info("Migrating/repairing %s records from x_bonds.orders", len(old_recs))

    legacy_to_new_created = {}  # ids creados en este post_init
    batch = []
    batch_old_ids = []

    def _flush_batch():
        nonlocal batch, batch_old_ids, legacy_to_new_created
        if not batch:
            return
        new_recs = New.sudo().create(batch)
        for o_id, n in zip(batch_old_ids, new_recs):
            legacy_to_new_created[o_id] = n.id
        batch = []
        batch_old_ids = []

    # ---------------------------------------------------------------------
    # Loop
    # ---------------------------------------------------------------------
    for o in old_recs:
        x_name = _old_get(o, "x_name", default=False)
        x_cliente = _old_get(o, "x_cliente", default=False)
        x_banco = _old_get(o, "x_banco", default=False)
        x_create = _old_get(o, "x_create", default=False)
        x_date = _old_get(o, "x_date", default=False)
        x_modo = _old_get(o, "x_modo", default=False)
        x_revisado = _old_get(o, "x_revisado", default=False)
        x_estado = _old_get(o, "x_estado", default=False)
        x_tipo = _old_get(o, "x_tipo", default=False)
        x_aval = _old_get(o, "x_aval", default=False)
        x_pedidos = _old_get(o, "x_pedidos", default=False)

        # Importes SIEMPRE por SQL
        x_importe, x_currency_id = _sql_old_amount_currency(o.id)

        # Reparación
        if o.id in bad_legacy_ids and o.id in legacy_to_new_id:
            new_rec = New.sudo().browse(legacy_to_new_id[o.id])
            upd = {}

            if (new_rec.amount in (0, 0.0, False, None)) and x_importe:
                upd["amount"] = float(x_importe)

            if not new_rec.currency_id:
                if x_currency_id:
                    upd["currency_id"] = int(x_currency_id)
                else:
                    upd["currency_id"] = env.company.currency_id.id

            if not new_rec.reference and x_name:
                upd["reference"] = x_name
            if not new_rec.name and x_name:
                upd["name"] = x_name

            if upd:
                new_rec.write(upd)
            continue

        # Crear
        vals = {
            "legacy_x_bonds_id": o.id,
            "reference": x_name or False,
            "name": x_name or False,
            "partner_id": x_cliente.id if x_cliente else False,
            "journal_id": x_banco.id if x_banco else False,
            "currency_id": int(x_currency_id) if x_currency_id else env.company.currency_id.id,
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

    # ---------------------------------------------------------------------
    # Re-enlazar chatter/actividades/adjuntos SOLO para los creados en este hook
    # ---------------------------------------------------------------------
    if legacy_to_new_created:
        old_ids_created = list(legacy_to_new_created.keys())

        msgs = env["mail.message"].sudo().search([
            ("model", "=", "x_bonds.orders"),
            ("res_id", "in", old_ids_created),
        ])
        for m in msgs:
            new_id = legacy_to_new_created.get(m.res_id)
            if new_id:
                m.write({"model": "sid_bonds_orders", "res_id": new_id})

        followers = env["mail.followers"].sudo().search([
            ("res_model", "=", "x_bonds.orders"),
            ("res_id", "in", old_ids_created),
        ])
        for f in followers:
            new_id = legacy_to_new_created.get(f.res_id)
            if new_id:
                f.write({"res_model": "sid_bonds_orders", "res_id": new_id})

        acts = env["mail.activity"].sudo().search([
            ("res_model", "=", "x_bonds.orders"),
            ("res_id", "in", old_ids_created),
        ])
        for a in acts:
            new_id = legacy_to_new_created.get(a.res_id)
            if new_id:
                a.write({"res_model": "sid_bonds_orders", "res_id": new_id})

        atts = env["ir.attachment"].sudo().search([
            ("res_model", "=", "x_bonds.orders"),
            ("res_id", "in", old_ids_created),
        ])
        for att in atts:
            new_id = legacy_to_new_created.get(att.res_id)
            if not new_id:
                continue
            vals = {"res_model": "sid_bonds_orders", "res_id": new_id}
            if att.res_field == "x_aval":
                vals["res_field"] = "pdf_aval"
            att.write(vals)

    # ---------------------------------------------------------------------
    # Re-enlazar Documents (si el módulo Documents está instalado)
    # ---------------------------------------------------------------------
    if "documents.document" in env and legacy_to_new_id:
        DD = env["documents.document"].sudo()

        # Para todos (creados y ya existentes), re-enlazamos docs antiguos a nuevo modelo.
        old_ids_all = list(legacy_to_new_id.keys())
        docs = DD.search([("res_model", "=", "x_bonds.orders"), ("res_id", "in", old_ids_all)])
        for d in docs:
            new_id = legacy_to_new_id.get(d.res_id)
            if not new_id:
                continue
            upd = {"res_model": "sid_bonds_orders", "res_id": new_id}
            if avales_folder and d.folder_id.id != avales_folder.id:
                upd["folder_id"] = avales_folder.id
            d.write(upd)

        # Si hay docs sueltos basados en attachment que hemos re-enlazado, los metemos en AVALES.
        if avales_folder:
            docs2 = DD.search([("res_model", "=", "sid_bonds_orders"), ("folder_id", "=", False)])
            if docs2:
                docs2.write({"folder_id": avales_folder.id})

    _logger.info("post_init_migrate_from_studio finished.")
