"""
Tests de la numérotation séquentielle sans trou.

Ces tests sont COMPLIANCE-CRITICAL : la DGI exige une numérotation
chronologique, séquentielle et sans trou par exercice fiscal.
"""
import pytest
from app.services.numbering import _allocate_next_number, MASK_INVOICE, MASK_CREDIT_NOTE


class TestNumberingAllocation:
    """Vérifie que l'allocation des numéros est correcte."""

    def test_first_number_is_1(self, session, company_id):
        """Le premier numéro d'un exercice doit être 1."""
        num = _allocate_next_number(session, company_id, 2026, "invoice", MASK_INVOICE)
        assert num == "F-2026-000001"

    def test_second_number_is_2(self, session, company_id):
        """Le second numéro doit être 2."""
        _allocate_next_number(session, company_id, 2026, "invoice", MASK_INVOICE)
        num = _allocate_next_number(session, company_id, 2026, "invoice", MASK_INVOICE)
        assert num == "F-2026-000002"

    def test_sequential_monotonic(self, session, company_id):
        """Les numéros doivent être strictement croissants."""
        nums = []
        for _ in range(100):
            num = _allocate_next_number(session, company_id, 2026, "invoice", MASK_INVOICE)
            nums.append(num)
        for i in range(1, len(nums)):
            # Vérifie que le dernier segment numérique croît de 1
            prev = int(nums[i - 1].split("-")[-1])
            curr = int(nums[i].split("-")[-1])
            assert curr == prev + 1

    def test_different_years_independent(self, session, company_id):
        """Les séquences par exercice fiscal doivent être indépendantes."""
        n1 = _allocate_next_number(session, company_id, 2026, "invoice", MASK_INVOICE)
        n2 = _allocate_next_number(session, company_id, 2027, "invoice", MASK_INVOICE)
        assert n1 == "F-2026-000001"
        assert n2 == "F-2027-000001"

    def test_credit_note_separate_sequence(self, session, company_id):
        """Les avoirs doivent avoir leur propre séquence indépendante."""
        inv_num = _allocate_next_number(session, company_id, 2026, "invoice", MASK_INVOICE)
        cn_num = _allocate_next_number(session, company_id, 2026, "credit_note", MASK_CREDIT_NOTE)
        assert inv_num == "F-2026-000001"
        assert cn_num == "AV-2026-000001"

    def test_different_companies_independent(self, session, company_id):
        """Deux entreprises différentes doivent avoir des séquences indépendantes."""
        c2_id = "22222222-2222-2222-2222-222222222222"
        n1 = _allocate_next_number(session, company_id, 2026, "invoice", MASK_INVOICE)
        n2 = _allocate_next_number(session, c2_id, 2026, "invoice", MASK_INVOICE)
        assert n1 == "F-2026-000001"
        assert n2 == "F-2026-000001"

    def test_no_gaps_on_sequential_allocation(self, session, company_id):
        """Sans annulation ni rollback, la séquence ne doit pas avoir de trous."""
        allocated = []
        for _ in range(10):
            num = _allocate_next_number(session, company_id, 2026, "invoice", MASK_INVOICE)
            allocated.append(int(num.split("-")[-1]))
        expected = list(range(1, 11))
        assert allocated == expected
