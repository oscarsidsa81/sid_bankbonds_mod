# -*- coding: utf-8 -*-

from . import models
from . import hooks
# Odoo expects the hook function to be importable from the module top-level
# (odoo.addons.<module_name>), so we re-export it here.
from .hooks import post_init_migrate_from_studio  # noqa: F401
