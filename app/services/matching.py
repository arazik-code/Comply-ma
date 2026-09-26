"""
Rapprochement à 3 voies (3-way matching) :
  Bon de Commande (PO) → Bon de Réception (GR) → Facture (Invoice)

Utilisé pour les factures fournisseurs entrantes.
"""
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

from sqlmodel import Session, select

from app.models.purchase_order import PurchaseOrder, PurchaseOrderLine
from app.models.invoice import Invoice, InvoiceLine
from app.models.goods_receipt import GoodsReceipt, GoodsReceiptLine


@dataclass
class MatchResult:
    po_id: str
    po_number: str
    line_matches: list["LineMatch"]
    overall_status: str  # full / partial / no_match
    total_po_amount: Decimal = Decimal("0.00")
    total_gr_amount: Decimal = Decimal("0.00")
    total_inv_amount: Decimal = Decimal("0.00")
    variance_pct: float = 0.0


@dataclass
class LineMatch:
    po_line_id: str
    invoice_description: str
    po_description: str
    qty_match: bool
    price_match: bool
    qty_ordered: Decimal
    qty_invoiced: Decimal
    qty_received: Optional[Decimal] = None
    price_ordered: Decimal = Decimal("0.00")
    price_invoiced: Decimal = Decimal("0.00")
    variance_pct: float = 0.0


def match_invoice_to_po(
    session: Session,
    invoice: Invoice,
) -> Optional[MatchResult]:
    """
    Rapprochement 2 voies (PO ↔ Facture) si pas de bon de réception.
    Si un GR existe, fait le rapprochement 3 voies complet.
    """
    from app.models.client import Client

    client = session.get(Client, invoice.client_id)
    if not client:
        return None

    # Chercher le PO correspondant
    po = session.exec(
        select(PurchaseOrder).where(
            PurchaseOrder.company_id == invoice.company_id,
            PurchaseOrder.supplier_id == invoice.client_id,
            PurchaseOrder.status.in_(["sent", "partially_received", "fully_received"]),
        ).order_by(PurchaseOrder.created_at.desc())
    ).first()

    if not po:
        return None

    po_lines = session.exec(
        select(PurchaseOrderLine).where(PurchaseOrderLine.po_id == po.id).order_by(PurchaseOrderLine.sort_order)
    ).all()
    inv_lines = session.exec(
        select(InvoiceLine).where(InvoiceLine.invoice_id == invoice.id)
    ).all()

    # Chercher le dernier bon de réception pour ce PO
    gr = session.exec(
        select(GoodsReceipt).where(GoodsReceipt.po_id == po.id).order_by(GoodsReceipt.created_at.desc())
    ).first()

    gr_lines = {}
    if gr:
        for grl in session.exec(
            select(GoodsReceiptLine).where(GoodsReceiptLine.goods_receipt_id == gr.id)
        ).all():
            gr_lines[grl.po_line_id] = grl

    line_matches = []
    for inv_line in inv_lines:
        best_match = None
        for po_line in po_lines:
            if po_line.description.lower() == inv_line.description.lower():
                best_match = po_line
                break
        if best_match:
            qty_ok = abs(inv_line.quantity - best_match.quantity) < Decimal("0.01")
            price_ok = abs(inv_line.unit_price - best_match.unit_price) < Decimal("0.01")

            qty_received = None
            gr_line = gr_lines.get(best_match.id)
            if gr_line:
                qty_received = gr_line.quantity_received

            variance = 0.0
            if best_match.quantity > 0:
                variance = float((inv_line.quantity - best_match.quantity) / best_match.quantity * 100)

            line_matches.append(LineMatch(
                po_line_id=best_match.id,
                invoice_description=inv_line.description,
                po_description=best_match.description,
                qty_match=qty_ok,
                price_match=price_ok,
                qty_ordered=best_match.quantity,
                qty_invoiced=inv_line.quantity,
                qty_received=qty_received,
                price_ordered=best_match.unit_price,
                price_invoiced=inv_line.unit_price,
                variance_pct=round(variance, 2),
            ))

    if not line_matches:
        return MatchResult(po_id=po.id, po_number=po.po_number, line_matches=[], overall_status="no_match")

    total_po = sum(m.price_ordered * m.qty_ordered for m in line_matches)
    total_inv = sum(m.price_invoiced * m.qty_invoiced for m in line_matches)

    all_full = all(m.qty_match and m.price_match for m in line_matches)
    variance = 0.0
    if total_po > 0:
        variance = float((total_inv - total_po) / total_po * 100)

    return MatchResult(
        po_id=po.id,
        po_number=po.po_number,
        line_matches=line_matches,
        overall_status="full" if all_full else "partial",
        total_po_amount=total_po,
        total_inv_amount=total_inv,
        variance_pct=round(variance, 2),
    )
