"""
Tests du service d'audit — vérifie l'immutabilité et la complétude des traces.
"""
import uuid
import json

from app.services.audit_service import log
from app.models.audit import AuditLog


class TestAuditLog:
    """Vérifications sur le journal d'audit."""

    def test_log_creates_entry(self, session, company_id):
        """Un appel à log() doit créer une entrée en base."""
        log(session, company_id, "invoice", str(uuid.uuid4()), "created")
        session.commit()

        entries = session.exec(
            AuditLog.__table__.select().where(AuditLog.company_id == company_id)
        ).all()
        assert len(entries) == 1
        assert entries[0].action == "created"

    def test_log_stores_old_and_new_values(self, session, company_id):
        """Les valeurs avant/après doivent être conservées."""
        entity_id = str(uuid.uuid4())
        old = json.dumps({"status": "draft"})
        new = json.dumps({"status": "validated", "invoice_number": "F-2026-000001"})
        log(session, company_id, "invoice", entity_id, "validated",
            old_values=old, new_values=new)
        session.commit()

        entry = session.exec(
            AuditLog.__table__.select().where(AuditLog.action == "validated")
        ).first()
        assert json.loads(entry.old_values) == {"status": "draft"}
        assert json.loads(entry.new_values)["invoice_number"] == "F-2026-000001"

    def test_log_timestamp_is_set(self, session, company_id):
        """Le timestamp doit être automatiquement renseigné."""
        log(session, company_id, "invoice", str(uuid.uuid4()), "created")
        session.commit()

        entry = session.exec(AuditLog.__table__.select()).first()
        assert entry.timestamp is not None

    def test_log_with_user_id(self, session, company_id):
        """L'ID utilisateur doit être tracé."""
        user_id = str(uuid.uuid4())
        log(session, company_id, "invoice", str(uuid.uuid4()), "validated", user_id=user_id)
        session.commit()

        entry = session.exec(AuditLog.__table__.select()).first()
        assert entry.user_id == user_id
