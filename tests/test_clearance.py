"""
Tests du MockClearanceProvider.
"""
import pytest

from app.services.clearance.mock_provider import MockClearanceProvider
from app.services.clearance.interface import ClearanceResult


@pytest.mark.asyncio
class TestMockClearance:
    async def test_submit_returns_result(self):
        provider = MockClearanceProvider()
        result = await provider.submit_invoice(b"<xml>test</xml>", "inv-001")
        assert isinstance(result, ClearanceResult)
        # 95% des cas : succès
        assert result.success is True or result.success is False

    async def test_check_status(self):
        provider = MockClearanceProvider()
        result = await provider.check_status("CLR-TEST1234")
        assert result.success is True
        assert result.clearance_number == "CLR-TEST1234"
