from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import zipfile


MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
MONTH_COLUMNS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "December"]
MONTH_NUMBER_BY_LABEL = {
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
    "SEPT": 9,
    "OCT": 10,
    "NOV": 11,
    "DEC": 12,
    "DECEMBER": 12,
}


@dataclass(frozen=True)
class ReverpointTenantRow:
    sheet_name: str
    sheet_label: str
    billing_year: int
    row_number: int
    unit_number: str
    tenant_name: str
    monthly_rent: Decimal
    parking_fee: Decimal
    month_statuses: dict[date, str]


def normalize_person_name(value: str) -> str:
    value = (value or "").strip()
    value = re.sub(r"\s+", " ", value)
    return "".join(char for char in value if char.isalnum()).upper()


def infer_parking_slots(total_fee: Decimal) -> tuple[int, int] | None:
    total_fee = Decimal(total_fee or 0).quantize(Decimal("0.01"))
    if total_fee == 0:
        return (0, 0)
    motorcycle_fee = Decimal("350.00")
    car_fee = Decimal("2500.00")
    matches: list[tuple[int, int]] = []
    max_cars = int(total_fee // car_fee)
    for cars in range(max_cars + 1):
        remainder = total_fee - (car_fee * cars)
        if remainder < 0:
            continue
        motorcycles = remainder / motorcycle_fee
        if motorcycles == int(motorcycles):
            matches.append((int(motorcycles), cars))
    if len(matches) != 1:
        return None
    return matches[0]


def parse_sheet_billing_year(sheet_label: str, *, year_mode: str = "end") -> int:
    matches = [int(match) for match in re.findall(r"(20\d{2})", sheet_label or "")]
    if not matches:
        raise ValueError(f"Could not determine billing year from sheet label: {sheet_label!r}")
    return matches[0] if year_mode == "start" else matches[-1]


def parse_reverpoint_workbook(path: str | Path, *, year_mode: str = "end") -> list[ReverpointTenantRow]:
    workbook_path = Path(path)
    if not workbook_path.exists():
        raise FileNotFoundError(f"Workbook not found: {workbook_path}")

    with zipfile.ZipFile(workbook_path) as archive:
        shared_strings = _read_shared_strings(archive)
        sheets = _read_workbook_sheets(archive)
        tenant_rows: list[ReverpointTenantRow] = []
        for sheet_name, worksheet_path in sheets:
            row_cells = _read_worksheet_rows(archive, worksheet_path, shared_strings)
            tenant_rows.extend(_extract_sheet_rows(sheet_name, row_cells, year_mode=year_mode))
        return tenant_rows


def _read_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    try:
        root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    except KeyError:
        return []

    values: list[str] = []
    for shared in root.findall(f"{{{MAIN_NS}}}si"):
        text = "".join(node.text or "" for node in shared.iterfind(f".//{{{MAIN_NS}}}t"))
        values.append(text)
    return values


def _read_workbook_sheets(archive: zipfile.ZipFile) -> list[tuple[str, str]]:
    workbook_root = ET.fromstring(archive.read("xl/workbook.xml"))
    rels_root = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    rel_map = {
        rel.attrib["Id"]: rel.attrib["Target"].lstrip("/")
        for rel in rels_root.findall(f"{{{PKG_REL_NS}}}Relationship")
    }

    sheets: list[tuple[str, str]] = []
    for sheet in workbook_root.findall(f".//{{{MAIN_NS}}}sheet"):
        rel_id = sheet.attrib.get(f"{{{REL_NS}}}id")
        if not rel_id or rel_id not in rel_map:
            continue
        target = rel_map[rel_id]
        if not target.startswith("xl/"):
            target = f"xl/{target}"
        sheets.append((sheet.attrib.get("name", ""), target))
    return sheets


def _read_worksheet_rows(
    archive: zipfile.ZipFile,
    worksheet_path: str,
    shared_strings: list[str],
) -> list[dict[int, str]]:
    worksheet_root = ET.fromstring(archive.read(worksheet_path))
    rows: list[dict[int, str]] = []
    for row in worksheet_root.findall(f".//{{{MAIN_NS}}}sheetData/{{{MAIN_NS}}}row"):
        cell_map: dict[int, str] = {}
        for cell in row.findall(f"{{{MAIN_NS}}}c"):
            ref = cell.attrib.get("r", "")
            col_index = _column_letters_to_index(re.sub(r"\d", "", ref))
            cell_map[col_index] = _cell_value(cell, shared_strings)
        rows.append(cell_map)
    return rows


def _cell_value(cell: ET.Element, shared_strings: list[str]) -> str:
    cell_type = cell.attrib.get("t", "")
    if cell_type == "inlineStr":
        return "".join(node.text or "" for node in cell.iterfind(f".//{{{MAIN_NS}}}t")).strip()
    raw_value = cell.findtext(f"{{{MAIN_NS}}}v", default="")
    if cell_type == "s":
        try:
            return shared_strings[int(raw_value)].strip()
        except (IndexError, ValueError):
            return ""
    return (raw_value or "").strip()


def _column_letters_to_index(letters: str) -> int:
    index = 0
    for char in letters:
        if not char.isalpha():
            continue
        index = (index * 26) + (ord(char.upper()) - 64)
    return index


def _extract_sheet_rows(
    sheet_name: str,
    rows: list[dict[int, str]],
    *,
    year_mode: str,
) -> list[ReverpointTenantRow]:
    header_index = _find_header_row_index(rows)
    if header_index is None:
        return []

    sheet_label = _sheet_label(rows, fallback=sheet_name)
    billing_year = parse_sheet_billing_year(sheet_label, year_mode=year_mode)
    header_row = rows[header_index]
    month_columns = _month_column_map(header_row, billing_year)
    extracted: list[ReverpointTenantRow] = []

    for row_number, row in enumerate(rows[header_index + 1 :], start=header_index + 2):
        unit_number, tenant_name = _split_unit_and_name(row.get(1, ""))
        if not unit_number or not tenant_name:
            continue

        monthly_rent = _to_decimal(row.get(2, "0"))
        parking_fee = _to_decimal(row.get(3, "0"))
        statuses = {
            month_date: (row.get(column_index, "") or "").strip().upper()
            for column_index, month_date in month_columns.items()
            if (row.get(column_index, "") or "").strip()
        }
        extracted.append(
            ReverpointTenantRow(
                sheet_name=sheet_name,
                sheet_label=sheet_label,
                billing_year=billing_year,
                row_number=row_number,
                unit_number=unit_number,
                tenant_name=tenant_name,
                monthly_rent=monthly_rent,
                parking_fee=parking_fee,
                month_statuses=statuses,
            )
        )

    return extracted


def _find_header_row_index(rows: list[dict[int, str]]) -> int | None:
    for index, row in enumerate(rows):
        first = (row.get(1, "") or "").strip().upper()
        second = (row.get(2, "") or "").strip().upper()
        third = (row.get(3, "") or "").strip().upper()
        if first == "NAME" and second == "UNIT PRICE" and third == "P/FEE":
            return index
    return None


def _sheet_label(rows: list[dict[int, str]], *, fallback: str) -> str:
    for row in rows[:3]:
        texts = [value.strip() for value in row.values() if value and value.strip()]
        if not texts:
            continue
        combined = " ".join(texts)
        if re.search(r"20\d{2}", combined):
            return combined
    return fallback


def _month_column_map(header_row: dict[int, str], billing_year: int) -> dict[int, date]:
    columns: dict[int, date] = {}
    for column_index, label in header_row.items():
        month = MONTH_NUMBER_BY_LABEL.get((label or "").strip().upper())
        if month is None:
            continue
        columns[column_index] = date(billing_year, month, 1)
    return columns


def _split_unit_and_name(value: str) -> tuple[str, str]:
    value = (value or "").strip()
    if not value or "-" not in value:
        return "", ""
    unit, tenant = value.split("-", 1)
    return unit.strip(), tenant.strip()


def _to_decimal(value: str) -> Decimal:
    cleaned = re.sub(r"[^0-9.\-]", "", (value or "").strip())
    if not cleaned:
        return Decimal("0.00")
    try:
        return Decimal(cleaned).quantize(Decimal("0.01"))
    except InvalidOperation:
        return Decimal("0.00")
