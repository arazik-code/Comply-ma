"""
Factures fournisseurs entrantes — réception via API, validation DGI, rapprochement 3 voies.
Supporte la saisie manuelle ET l'upload de XML UBL 2.1.
"""
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Request, Depends, UploadFile, File, Form
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlmodel import Session, select, func

from app.database import get_session
from app.pagination import Page, PAGE_SIZE
from app.models.invoice import Invoice, InvoiceLine
from app.models.client import Client
from app.models.company import Company
from app.models.product import Product
from app.models.purchase_order import PurchaseOrder
from app.services.auth import require_auth
from app.services.matching import match_invoice_to_po
from app.services.hash_service import compute_hash
from app.services.compliance_engine import check_invoice
from app.i18n import get_translator
from app.flash import flash
from app.templating import templates

logger = logging.getLogger("app.supplier_invoices")
router = APIRouter(dependencies=[Depends(require_auth)])


@router.get("/supplier-invoices/receive-form", response_class=HTMLResponse)
async def supplier_invoice_receive_form(request: Request, session: Session = Depends(get_session)):
    t = get_translator(request)
    user = require_auth(request)
    company_id = user["company_id"]
    suppliers = session.exec(
        select(Client).where(Client.company_id == company_id).order_by(Client.name)
    ).all()
    company = session.get(Company, company_id)
    return templates.TemplateResponse(request, "supplier_invoices/form.html", {
        "t": t, "user": user, "suppliers": suppliers, "company": company,
    })


@router.get("/supplier-invoices/upload-form", response_class=HTMLResponse)
async def supplier_invoice_upload_form(request: Request, session: Session = Depends(get_session)):
    t = get_translator(request)
    user = require_auth(request)
    company_id = user["company_id"]
    suppliers = session.exec(
        select(Client).where(Client.company_id == company_id).order_by(Client.name)
    ).all()
    company = session.get(Company, company_id)
    return templates.TemplateResponse(request, "supplier_invoices/upload.html", {
        "t": t, "user": user, "suppliers": suppliers, "company": company,
    })


@router.get("/supplier-invoices", response_class=HTMLResponse)
async def supplier_invoice_list(
    request: Request,
    status: str = "",
    page: int = 1,
    session: Session = Depends(get_session),
):
    t = get_translator(request)
    user = require_auth(request)
    company_id = user["company_id"]

    company = session.get(Company, company_id)
    stmt = select(Invoice).where(Invoice.company_id == company_id, Invoice.is_supplier_invoice == True)
    count_stmt = select(func.count()).select_from(Invoice).where(Invoice.company_id == company_id, Invoice.is_supplier_invoice == True)

    if status:
        stmt = stmt.where(Invoice.status == status)
        count_stmt = count_stmt.where(Invoice.status == status)

    total = session.exec(count_stmt).one()
    items = session.exec(stmt.order_by(Invoice.created_at.desc()).offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE)).all()

    page_obj = Page(items=items, page=page, page_size=PAGE_SIZE, total=total)
    suppliers = {}
    for inv in items:
        s = session.get(Client, inv.client_id)
        suppliers[inv.client_id] = s

    return templates.TemplateResponse(request, "supplier_invoices/list.html", {
        "t": t, "user": user, "page_obj": page_obj, "status": status, "suppliers": suppliers, "company": company,
    })


@router.get("/supplier-invoices/{invoice_id}", response_class=HTMLResponse)
async def supplier_invoice_detail(invoice_id: str, request: Request, session: Session = Depends(get_session)):
    t = get_translator(request)
    user = require_auth(request)
    invoice = session.get(Invoice, invoice_id)
    if not invoice or invoice.company_id != user["company_id"] or not invoice.is_supplier_invoice:
        return RedirectResponse(url="/supplier-invoices", status_code=303)
    lines = session.exec(
        select(InvoiceLine).where(InvoiceLine.invoice_id == invoice_id).order_by(InvoiceLine.sort_order)
    ).all()
    supplier = session.get(Client, invoice.client_id)
    company = session.get(Company, invoice.company_id)

    match_result = match_invoice_to_po(session, invoice)

    # Compliance check
    tva_rates = {}
    from app.models.tva import TVARate
    for rate in session.exec(select(TVARate).where(TVARate.company_id == invoice.company_id, TVARate.is_active == True)):
        tva_rates[str(rate.id)] = rate
    compliance = check_invoice(invoice, lines, supplier, company, tva_rates)

    return templates.TemplateResponse(request, "supplier_invoices/detail.html", {
        "t": t, "user": user, "invoice": invoice, "lines": lines,
        "supplier": supplier, "company": company, "match_result": match_result,
        "compliance": compliance,
    })


@router.post("/supplier-invoices/receive", response_class=HTMLResponse)
async def supplier_invoice_receive(
    request: Request,
    supplier_id: str = Form(...),
    invoice_date: str = Form(...),
    invoice_number: str = Form(""),
    total_ht: str = Form("0"),
    total_tva: str = Form("0"),
    total_ttc: str = Form("0"),
    session: Session = Depends(get_session),
):
    user = require_auth(request)
    company_id = user["company_id"]
    invoice = Invoice(
        company_id=company_id,
        client_id=supplier_id,
        fiscal_year=datetime.now(timezone.utc).year,
        invoice_date=datetime.strptime(invoice_date, "%Y-%m-%d").replace(tzinfo=timezone.utc),
        invoice_number=invoice_number or None,
        status="received",
        is_supplier_invoice=True,
        total_ht=Decimal(total_ht),
        total_tva=Decimal(total_tva),
        total_ttc=Decimal(total_ttc),
    )
    session.add(invoice)
    session.commit()
    flash(request, "Facture fournisseur enregistrée")
    return RedirectResponse(url=f"/supplier-invoices/{invoice.id}", status_code=303)


@router.post("/supplier-invoices/upload", response_class=HTMLResponse)
async def supplier_invoice_upload(
    request: Request,
    xml_file: UploadFile = File(...),
    supplier_id: str = Form(""),
    session: Session = Depends(get_session),
):
    """
    Upload et parse une facture fournisseur en UBL 2.1 XML.
    Extrait les données, crée la facture et les lignes.
    """
    user = require_auth(request)
    company_id = user["company_id"]

    xml_bytes = await xml_file.read()

    try:
        from lxml import etree
        # Parseur durci : pas d'entités externes (XXE), pas de réseau, pas de DTD
        parser = etree.XMLParser(
            resolve_entities=False,
            no_network=True,
            dtd_validation=False,
            load_dtd=False,
            huge_tree=False,
        )
        root = etree.fromstring(xml_bytes, parser)
    except Exception as e:
        flash(request, f"XML invalide: {e}", "error")
        return RedirectResponse(url="/supplier-invoices/upload-form", status_code=303)

    ns = {
        "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
        "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
    }

    def _find(tag):
        return root.find(f"{{http://urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}}{tag}")

    def _find_all(tag):
        return root.findall(f"{{http://urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2}}{tag}")

    # Extraire les données
    invoice_number_el = _find("ID")
    invoice_number = invoice_number_el.text if invoice_number_el is not None else None

    issue_date_el = _find("IssueDate")
    issue_date = datetime.strptime(issue_date_el.text, "%Y-%m-%d").replace(tzinfo=timezone.utc) if issue_date_el is not None else datetime.now(timezone.utc)

    # Trouver le client/fournisseur
    client = None
    if supplier_id:
        client = session.get(Client, supplier_id)
    if not client:
        # Chercher par ICE dans le XML
        ice_el = root.find(".//{http://urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}ID[@schemeID='ICE']")
        if ice_el is not None and ice_el.text:
            client = session.exec(
                select(Client).where(Client.company_id == company_id, Client.ice == ice_el.text)
            ).first()

    if not client:
        flash(request, "Fournisseur introuvable — spécifiez le fournisseur", "error")
        return RedirectResponse(url="/supplier-invoices/upload-form", status_code=303)

    # Extraire les totaux
    monetary = root.find("{http://urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2}LegalMonetaryTotal")
    total_ht = Decimal("0.00")
    total_tva = Decimal("0.00")
    total_ttc = Decimal("0.00")
    if monetary is not None:
        ht_el = monetary.find("{http://urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}TaxExclusiveAmount")
        ttc_el = monetary.find("{http://urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}TaxInclusiveAmount")
        if ht_el is not None:
            total_ht = Decimal(ht_el.text or "0")
        if ttc_el is not None:
            total_ttc = Decimal(ttc_el.text or "0")
        total_tva = total_ttc - total_ht

    # Créer la facture
    invoice = Invoice(
        company_id=company_id,
        client_id=client.id,
        fiscal_year=issue_date.year,
        invoice_date=issue_date,
        invoice_number=invoice_number,
        status="received",
        is_supplier_invoice=True,
        total_ht=total_ht,
        total_tva=total_tva,
        total_ttc=total_ttc,
        hash_sha256=compute_hash(xml_bytes),
        hash_algorithm="sha256",
    )
    session.add(invoice)
    session.flush()

    # Extraire les lignes
    inv_lines = _find_all("InvoiceLine")
    for i, line_el in enumerate(inv_lines):
        desc_el = line_el.find(".//{http://urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}Name")
        qty_el = line_el.find("{http://urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}InvoicedQuantity")
        ext_el = line_el.find("{http://urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}LineExtensionAmount")
        price_el = line_el.find(".//{http://urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}PriceAmount")

        description = desc_el.text if desc_el is not None else f"Ligne {i+1}"
        quantity = Decimal(qty_el.text or "1") if qty_el is not None else Decimal("1")
        ext_amount = Decimal(ext_el.text or "0") if ext_el is not None else Decimal("0")
        unit_price = Decimal(price_el.text or "0") if price_el is not None else Decimal("0")

        # Calculer la TVA à partir du taux
        rate_el = line_el.find(".//{http://urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}Percent")
        tva_rate = Decimal("0.20")
        if rate_el is not None:
            try:
                tva_rate = Decimal(rate_el.text) / Decimal("100")
            except Exception:
                pass

        line_tva = ext_amount * tva_rate
        line_ttc = ext_amount + line_tva

        inv_line = InvoiceLine(
            invoice_id=invoice.id,
            description=description[:500],
            quantity=quantity,
            unit_price=unit_price,
            tva_rate=tva_rate,
            line_total_ht=ext_amount,
            line_total_tva=line_tva,
            line_total_ttc=line_ttc,
            sort_order=i + 1,
        )
        session.add(inv_line)

    # Hash de la chaîne
    invoice.hash_chain_previous = compute_hash(xml_bytes)
    session.add(invoice)
    session.commit()

    flash(request, f"Facture {invoice_number or '(sans numéro)'} importée avec {len(inv_lines)} ligne(s)")
    return RedirectResponse(url=f"/supplier-invoices/{invoice.id}", status_code=303)
