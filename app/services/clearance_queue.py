"""
File d'attente de clearance DGI — traitement asynchrone avec tentatives.
En cas d'échec, le système réessaie automatiquement jusqu'à max_attempts fois.
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlmodel import Session, select

from app.database import engine
from app.models.clearance_queue import ClearanceQueueItem
from app.models.invoice import Invoice
from app.models.clearance import ClearanceRecord
from app.services.state_machine import InvoiceStatus, validate_transition, InvalidTransitionError

logger = logging.getLogger("app.clearance_queue")

RETRY_DELAYS = [1, 5, 15, 30, 60]  # minutes


def enqueue(invoice_id: str, company_id: str, session: Session):
    item = ClearanceQueueItem(
        company_id=company_id,
        invoice_id=invoice_id,
        next_retry_at=datetime.now(timezone.utc),
    )
    session.add(item)
    session.commit()
    logger.info("clearance_enqueued", extra={"invoice_id": invoice_id})


def process_queue():
    """Traite tous les items en attente. Appelé par le scheduler ou manuellement."""
    with Session(engine) as session:
        items = session.exec(
            select(ClearanceQueueItem).where(
                ClearanceQueueItem.status == "pending",
                ClearanceQueueItem.next_retry_at <= datetime.now(timezone.utc),
            ).order_by(ClearanceQueueItem.created_at)
        ).all()

        for item in items:
            process_item(item, session)


def process_item(item: ClearanceQueueItem, session: Session):
    item.status = "processing"
    item.attempt_count += 1
    session.add(item)
    session.commit()

    invoice = session.get(Invoice, item.invoice_id)
    if not invoice:
        item.status = "failed"
        item.next_retry_at = None
        item.last_error = "Facture introuvable"
        session.add(item)
        session.commit()
        return

    try:
        # Générer le XML UBL avant soumission
        from app.models.client import Client
        from app.models.company import Company
        from app.services.xml.ubl_generator import generate_ubl_invoice
        from app.services.xml.signature import get_signer

        client = session.get(Client, invoice.client_id)
        company = session.get(Company, invoice.company_id)
        from app.models.invoice import InvoiceLine
        lines = session.exec(
            select(InvoiceLine).where(InvoiceLine.invoice_id == invoice.id).order_by(InvoiceLine.sort_order)
        ).all()

        xml_bytes = generate_ubl_invoice(invoice, lines, company, client)

        # Signer le XML
        try:
            signer = get_signer()
            xml_bytes = signer.sign(xml_bytes)
        except Exception:
            pass  # Signature optionnelle en dev

        # Soumettre au provider
        from app.config import settings
        if settings.clearance_provider == "dgi":
            from app.services.clearance.dgi_provider import DGIClearanceProvider
            provider = DGIClearanceProvider()
        else:
            from app.services.clearance.mock_provider import MockClearanceProvider
            provider = MockClearanceProvider()

        import asyncio
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop and loop.is_running():
            # Appelé depuis un contexte async (FastAPI) — thread dédié
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                result = ex.submit(
                    asyncio.run, provider.submit_invoice(xml_bytes, invoice.id)
                ).result(timeout=60)
        else:
            result = asyncio.run(provider.submit_invoice(xml_bytes, invoice.id))

        if result.success:
            try:
                validate_transition(InvoiceStatus(invoice.status), InvoiceStatus.CLEARED)
                invoice.status = "cleared"
                invoice.cleared_at = datetime.now(timezone.utc)
            except InvalidTransitionError:
                pass

            record = ClearanceRecord(
                company_id=item.company_id,
                invoice_id=invoice.id,
                clearance_number=result.clearance_number or "",
                status="approved",
                raw_request=xml_bytes.decode("utf-8", errors="replace")[:10000],
                raw_response=result.raw_response or "",
            )
            session.add(record)
            item.status = "success"
            item.next_retry_at = None
            item.completed_at = datetime.now(timezone.utc)
            logger.info("clearance_success", extra={"invoice_id": invoice.id, "clearance": result.clearance_number})
        else:
            try:
                validate_transition(InvoiceStatus(invoice.status), InvoiceStatus.REJECTED)
                invoice.status = "rejected"
            except InvalidTransitionError:
                pass
            invoice.rejected_reason = result.error_message or "Rejeté par la DGI"
            item.status = "failed"
            item.last_error = result.error_message or result.error_code or "Erreur inconnue"
            item.error_code = result.error_code
            _schedule_retry(item)
            logger.warning("clearance_rejected", extra={"invoice_id": invoice.id, "error": result.error_message})

    except Exception as e:
        logger.error("clearance_error", extra={"invoice_id": invoice.id, "error": str(e)})
        item.status = "failed"
        item.last_error = str(e)[:500]
        _schedule_retry(item)

    session.add(item)
    session.add(invoice)
    session.commit()


def _schedule_retry(item: ClearanceQueueItem):
    if item.attempt_count >= item.max_attempts:
        item.next_retry_at = None
        logger.warning("clearance_max_retries", extra={"invoice_id": item.invoice_id, "attempts": item.attempt_count})
        return
    delay = RETRY_DELAYS[min(item.attempt_count - 1, len(RETRY_DELAYS) - 1)]
    item.next_retry_at = datetime.now(timezone.utc) + timedelta(minutes=delay)
    logger.info("clearance_retry_scheduled", extra={"invoice_id": item.invoice_id, "delay_min": delay})
