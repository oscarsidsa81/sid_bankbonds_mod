# -*- coding: utf-8 -*-
import re
from odoo import _
from odoo.exceptions import UserError

# ------------------------------
# Helpers de ámbito
# ------------------------------
def _get_root_workspace(self):
    root = self._get_folder_by_xmlid(self.XMLID_FACETS_SOURCE_FOLDER)
    if not root:
        raise UserError(_("No existe el workspace raíz (%s).") % self.XMLID_FACETS_SOURCE_FOLDER)
    return root

def _scoped_domain(self, extra=None):
    """
    Limita a ROOT y excluye Archivado (_todo su subárbol).
    Se llama como _scoped_domain(self, extra), donde self suele ser sale.order.
    """
    extra = list(extra or [])
    root = _get_root_workspace(self)
    exclude = self._get_folder_by_xmlid(self.XMLID_EXCLUDE_FOLDER)
    dom = [('id', 'child_of', root.id)]
    if exclude:
        dom += ['!', ('id', 'child_of', exclude.id)]
    return dom + extra

# ------------------------------
# Parser de códigos
# ------------------------------
CODE_RE = re.compile(r'^(?P<digits>\d+)(?P<letter>[A-Z]+)?(?:_(?P<rev>\d+))?$')

def _parse_code(self, name):
    """
    LSG-CN-PU-CON-0018D_03 -> {
      'prefix': 'LSG-CN-PU', 'type': 'CON', 'digits': '0018',
      'letter': 'D', 'rev': '03'
    }
    """
    toks = [t for t in (name or '').strip().upper().split('-') if t]
    if len(toks) < 2:
        return {}
    typ = toks[-2]
    last = toks[-1]
    m = CODE_RE.match(last)
    if not m:
        return {}
    return {
        'prefix': '-'.join(toks[:-2]) if len(toks) > 2 else '',
        'type': typ,
        'digits': m.group('digits') or '',
        'letter': m.group('letter') or '',
        'rev': m.group('rev') or '',
    }

def _candidate_basenames(self, name):
    """
    Devuelve candidatos (más específico primero) respetando el TIPO.
    Ej.: ...-CON-5069A -> ['...-CON-5069A', '...-CON-5069']
         ...-CON-0018D_03 -> ['...-CON-0018D', '...-CON-0018']
         ...-VAO-0018 -> ['...-VAO-0018']
    """
    p = _parse_code(self, name)
    if not p or not p.get('type') or not p.get('digits'):
        return []
    base_with_letter = f"{p['digits']}{p['letter']}" if p.get('letter') else None
    prefix = f"{p['prefix']}-{p['type']}" if p.get('prefix') else p['type']
    candidates = []
    if base_with_letter:
        candidates.append(f"{prefix}-{base_with_letter}")
    candidates.append(f"{prefix}-{p['digits']}")
    return candidates
