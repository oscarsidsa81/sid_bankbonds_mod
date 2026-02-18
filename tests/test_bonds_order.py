# -*- coding: utf-8 -*-

from odoo.tests.common import SavepointCase


class TestBondsOrder(SavepointCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Bond = cls.env["sid_bonds_orders"]

    def test_state_manage_reflects_state(self):
        bond = self.Bond.create({"reference": "BOND-TEST-001"})

        state_expectations = {
            "draft": "new",
            "requested": "new",
            "active": "current",
            "expired": "finished",
            "cancelled": "done",
        }

        for state, expected_manage in state_expectations.items():
            bond.write({"state": state})
            self.assertEqual(
                bond.state_manage,
                expected_manage,
                "state_manage debe reflejar correctamente el subestado",
            )

    def test_write_reference_syncs_name(self):
        bond = self.Bond.create({})
        bond.write({"reference": "REF-12345"})
        self.assertEqual(bond.name, "REF-12345")
