"""
Numbering Gap Detection — finds missing invoice numbers in a sequence.

DGI format: F000000001/2025 ... F000000010/2025
Detects: gaps, duplicates, non-sequential numbers, wrong-year numbers.
"""
import re
from dataclasses import dataclass, field
from typing import Optional

INVOICE_NUM_RE = re.compile(r"^F(\d{9})/(\d{4})$")
CREDIT_NOTE_NUM_RE = re.compile(r"^AV(\d{9})/(\d{4})$")
PO_NUM_RE = re.compile(r"^BC-(\d{6})-(\d{4})$")


@dataclass
class NumberingIssue:
    issue_type: str  # gap | duplicate | format | wrong_year | out_of_sequence
    severity: str    # error | warning
    detail: str
    number: str = ""
    expected: str = ""


@dataclass
class NumberingReport:
    fiscal_year: int
    invoice_type: str  # invoice | credit_note
    total_count: int
    issues: list[NumberingIssue] = field(default_factory=list)
    sequence_start: int = 0
    sequence_end: int = 0
    duplicates: list[str] = field(default_factory=list)
    gaps: list[dict] = field(default_factory=list)
    score: int = 100

    @property
    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "warning")


def detect_numbering_gaps(
    numbers: list[str],
    fiscal_year: int,
    invoice_type: str = "invoice",
) -> NumberingReport:
    """
    Analyze a list of invoice numbers for gaps, duplicates, and issues.
    """
    report = NumberingReport(fiscal_year=fiscal_year, invoice_type=invoice_type, total_count=len(numbers))

    pattern = INVOICE_NUM_RE if invoice_type == "invoice" else CREDIT_NOTE_NUM_RE
    prefix = "F" if invoice_type == "invoice" else "AV"

    parsed = []
    format_issues = []
    year_issues = []
    seen_numbers = {}

    for num in numbers:
        if not num:
            continue

        match = pattern.match(num)
        if not match:
            format_issues.append(NumberingIssue(
                issue_type="format", severity="error",
                detail=f"Format invalide: '{num}' (attendu: {prefix}000000001/{fiscal_year})",
                number=num,
            ))
            continue

        seq_str, year_str = match.groups()
        seq = int(seq_str)
        year = int(year_str)

        if year != fiscal_year:
            year_issues.append(NumberingIssue(
                issue_type="wrong_year", severity="warning",
                detail=f"Année {year} dans '{num}' — exercice attendu: {fiscal_year}",
                number=num,
            ))

        parsed.append((seq, num))

        if num in seen_numbers:
            report.duplicates.append(num)
            report.issues.append(NumberingIssue(
                issue_type="duplicate", severity="error",
                detail=f"Numéro dupliqué: '{num}'",
                number=num,
            ))
        seen_numbers[num] = True

    report.issues.extend(format_issues)
    report.issues.extend(year_issues)

    if not parsed:
        report.score = 100 if not format_issues else 50
        return report

    parsed.sort(key=lambda x: x[0])
    report.sequence_start = parsed[0][0]
    report.sequence_end = parsed[-1][0]

    # Detect gaps
    existing_seqs = {s for s, _ in parsed}
    expected_seqs = set(range(parsed[0][0], parsed[-1][0] + 1))
    gap_seqs = sorted(expected_seqs - existing_seqs)

    for gap_seq in gap_seqs:
        gap_num = f"{prefix}{gap_seq:09d}/{fiscal_year}"
        report.gaps.append({"expected": gap_num, "position": gap_seq})
        report.issues.append(NumberingIssue(
            issue_type="gap", severity="error",
            detail=f"Numéro manquant: '{gap_num}'",
            expected=gap_num,
        ))

    # Out-of-sequence (non-sequential ordering)
    prev_seq = None
    for seq, num in parsed:
        if prev_seq is not None and seq != prev_seq + 1:
            if seq - prev_seq > 1:
                pass  # Already caught as gap
        prev_seq = seq

    # Score
    error_count = report.error_count
    total_issues = len(report.issues)
    if total_issues == 0:
        report.score = 100
    else:
        report.score = max(0, 100 - (error_count * 15) - (report.warning_count * 5))

    return report


def suggest_next_number(existing_numbers: list[str], fiscal_year: int, invoice_type: str = "invoice") -> str:
    """Suggest the next invoice number in sequence."""
    pattern = INVOICE_NUM_RE if invoice_type == "invoice" else CREDIT_NOTE_NUM_RE
    prefix = "F" if invoice_type == "invoice" else "AV"

    max_seq = 0
    for num in existing_numbers:
        match = pattern.match(num)
        if match:
            seq_str, year_str = match.groups()
            if int(year_str) == fiscal_year:
                max_seq = max(max_seq, int(seq_str))

    return f"{prefix}{max_seq + 1:09d}/{fiscal_year}"
