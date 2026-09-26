"""
Data Import Wizard — ingest client invoices from Excel/CSV/manual paste.

Supports:
  - CSV/Excel upload (with column mapping)
  - Manual paste (WhatsApp messages, paper notes)
  - Auto-detect columns, validate on import, flag issues
"""
import csv
import io
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Optional


@dataclass
class ImportColumn:
    name: str
    mapped_to: str  # invoice_number, invoice_date, client_name, total_ht, total_tva, total_ttc, etc.
    detected_type: str = "text"  # text, number, date, currency


@dataclass
class ImportRow:
    row_number: int
    raw: dict
    mapped: dict
    issues: list[str] = field(default_factory=list)
    valid: bool = True


@dataclass
class ImportResult:
    filename: str
    total_rows: int
    valid_rows: int
    invalid_rows: int
    issues: list[dict] = field(default_factory=list)
    preview: list[dict] = field(default_factory=list)
    columns: list[ImportColumn] = field(default_factory=list)
    success: bool = True
    error: str = ""


# Known column name mappings (FR/EN/AR)
COLUMN_ALIASES = {
    "invoice_number": ["numéro", "numero", "number", "num facture", "n° facture", "invoice_number", "ref", "référence"],
    "invoice_date": ["date", "date facture", "date de facture", "invoice_date", "datum"],
    "client_name": ["client", "client_name", "nom client", "acheteur", "buyer"],
    "client_ice": ["ice client", "ice acheteur", "client ice"],
    "total_ht": ["ht", "total ht", "montant ht", "total_ht", "amount ht"],
    "total_tva": ["tva", "total tva", "montant tva", "total_tva"],
    "total_ttc": ["ttc", "total ttc", "montant ttc", "total_ttc", "total"],
    "tva_rate": ["taux tva", "tva rate", "rate", "taux"],
    "description": ["description", "objet", "désignation", "designation", "libellé", "libelle", "item"],
    "quantity": ["quantité", "quantite", "qty", "quantity", "qte"],
    "unit_price": ["prix unitaire", "unit_price", "pu", "price"],
}


def detect_columns(headers: list[str]) -> list[ImportColumn]:
    """Auto-detect column mapping from headers."""
    columns = []
    for header in headers:
        header_lower = header.lower().strip()
        mapped_to = ""
        for field_name, aliases in COLUMN_ALIASES.items():
            if any(alias in header_lower for alias in aliases):
                mapped_to = field_name
                break

        col_type = "text"
        if mapped_to in ("total_ht", "total_tva", "total_ttc", "tva_rate", "quantity", "unit_price"):
            col_type = "number"
        elif mapped_to == "invoice_date":
            col_type = "date"

        columns.append(ImportColumn(name=header, mapped_to=mapped_to or "unknown", detected_type=col_type))
    return columns


def parse_date(date_str: str) -> Optional[datetime]:
    """Parse various date formats common in Morocco."""
    if not date_str or not date_str.strip():
        return None
    date_str = date_str.strip()
    formats = ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y/%m/%d", "%d %m %Y"]
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def parse_decimal(value) -> Optional[Decimal]:
    """Parse decimal from various formats (1.234,56 or 1,234.56)."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None

    # Handle Moroccan/European format: 1.234,56
    if "," in s and "." in s:
        if s.rindex(",") > s.rindex("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        parts = s.split(",")
        if len(parts) == 2 and len(parts[1]) <= 2:
            s = s.replace(",", ".")
        else:
            s = s.replace(",", "")

    s = s.replace(" ", "").replace("MAD", "").replace("dh", "").strip()

    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def import_csv(file_content: str, filename: str = "import.csv") -> ImportResult:
    """Import invoices from CSV content."""
    try:
        # Detect delimiter
        sniffer = csv.Sniffer()
        dialect = sniffer.sniff(file_content[:4096])

        reader = csv.DictReader(io.StringIO(file_content), dialect=dialect)
        if not reader.fieldnames:
            return ImportResult(filename=filename, total_rows=0, valid_rows=0, invalid_rows=0, success=False, error="Aucune en-tête détectée")

        columns = detect_columns(list(reader.fieldnames))
        rows = []
        issues = []

        for idx, row in enumerate(reader, 1):
            import_row = _process_row(idx, row, columns)
            rows.append(import_row)
            if not import_row.valid:
                issues.append({"row": idx, "issues": import_row.issues})

        valid = sum(1 for r in rows if r.valid)
        preview = [r.mapped for r in rows[:10]]

        return ImportResult(
            filename=filename, total_rows=len(rows), valid_rows=valid,
            invalid_rows=len(rows) - valid, issues=issues, preview=preview,
            columns=columns,
        )
    except Exception as e:
        return ImportResult(filename=filename, total_rows=0, valid_rows=0, invalid_rows=0, success=False, error=str(e))


def import_paste(text: str) -> ImportResult:
    """Import from manual paste (WhatsApp messages, paper notes)."""
    lines = [l.strip() for l in text.strip().split("\n") if l.strip()]
    if not lines:
        return ImportResult(filename="paste", total_rows=0, valid_rows=0, invalid_rows=0, success=False, error="Texte vide")

    rows = []
    issues = []

    for idx, line in enumerate(lines, 1):
        mapped = {}
        row_issues = []

        # Try to extract invoice number
        num_match = re.search(r"F\d{9}/\d{4}", line)
        if num_match:
            mapped["invoice_number"] = num_match.group()

        # Try to extract date
        date_match = re.search(r"\d{2}[/-]\d{2}[/-]\d{4}", line)
        if date_match:
            mapped["invoice_date"] = date_match.group()

        # Try to extract amounts
        amounts = re.findall(r"[\d.,]+\s*(?:MAD|dh|DH)?", line)
        if amounts:
            for amt_str in amounts[:3]:
                amt = parse_decimal(amt_str)
                if amt is not None:
                    if "total_ttc" not in mapped:
                        mapped["total_ttc"] = str(amt)
                    elif "total_ht" not in mapped:
                        mapped["total_ht"] = str(amt)
                    elif "total_tva" not in mapped:
                        mapped["total_tva"] = str(amt)

        # Try to extract ICE
        ice_match = re.search(r"\b\d{15}\b", line)
        if ice_match:
            mapped["client_ice"] = ice_match.group()

        if not mapped:
            row_issues.append("Impossible d'extraire des données de cette ligne")

        rows.append(ImportRow(row_number=idx, raw={"text": line}, mapped=mapped, issues=row_issues, valid=bool(mapped)))
        if row_issues:
            issues.append({"row": idx, "issues": row_issues})

    valid = sum(1 for r in rows if r.valid)
    return ImportResult(
        filename="paste", total_rows=len(rows), valid_rows=valid,
        invalid_rows=len(rows) - valid, issues=issues,
        preview=[r.mapped for r in rows[:10]],
    )


def import_excel(file_content: bytes, filename: str = "import.xlsx") -> ImportResult:
    """Import from Excel file. Falls back to CSV if openpyxl not available."""
    try:
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(file_content), read_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            return ImportResult(filename=filename, total_rows=0, valid_rows=0, invalid_rows=0, success=False, error="Feuille vide")

        headers = [str(h) if h else "" for h in rows[0]]
        columns = detect_columns(headers)
        data_rows = rows[1:]
        import_rows = []
        issues = []

        for idx, row in enumerate(data_rows, 1):
            row_dict = {headers[i]: row[i] if i < len(row) else "" for i in range(len(headers))}
            import_row = _process_row(idx, row_dict, columns)
            import_rows.append(import_row)
            if not import_row.valid:
                issues.append({"row": idx, "issues": import_row.issues})

        valid = sum(1 for r in import_rows if r.valid)
        return ImportResult(
            filename=filename, total_rows=len(import_rows), valid_rows=valid,
            invalid_rows=len(import_rows) - valid, issues=issues,
            preview=[r.mapped for r in import_rows[:10]],
            columns=columns,
        )
    except ImportError:
        # Fallback: try reading as CSV
        try:
            text = file_content.decode("utf-8-sig")
            return import_csv(text, filename)
        except Exception:
            return ImportResult(filename=filename, total_rows=0, valid_rows=0, invalid_rows=0, success=False, error="openpyxl non installé et le fichier n'est pas un CSV valide")


def _process_row(idx: int, row: dict, columns: list[ImportColumn]) -> ImportRow:
    """Process a single row with column mapping."""
    mapped = {}
    issues = []

    for col in columns:
        value = row.get(col.name, "")
        if value is None:
            value = ""
        value = str(value).strip()

        if not value:
            continue

        if col.mapped_to == "invoice_date":
            parsed = parse_date(value)
            if parsed:
                mapped["invoice_date"] = parsed.strftime("%Y-%m-%d")
            else:
                issues.append(f"Date invalide: '{value}' (ligne {idx})")
        elif col.mapped_to in ("total_ht", "total_tva", "total_ttc", "tva_rate", "quantity", "unit_price"):
            parsed = parse_decimal(value)
            if parsed is not None:
                mapped[col.mapped_to] = str(parsed)
            else:
                issues.append(f"Montant invalide: '{value}' (ligne {idx})")
        else:
            mapped[col.mapped_to] = value

    # Validate required fields
    if not mapped.get("invoice_number") and not mapped.get("client_name"):
        issues.append(f"Ligne {idx}: numéro de facture ou nom client requis")

    return ImportRow(
        row_number=idx, raw=row, mapped=mapped,
        issues=issues, valid=len(issues) == 0,
    )
