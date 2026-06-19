from __future__ import annotations

from datetime import date
from pathlib import Path
import tempfile
from zipfile import ZipFile

from django.test import SimpleTestCase

from accounts.importers.reverpoint_workbook import (
    infer_parking_slots,
    normalize_person_name,
    parse_reverpoint_workbook,
    parse_sheet_billing_year,
)


CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>
</Types>
"""

ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>
"""

WORKBOOK_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
          xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="Sheet1" sheetId="1" r:id="rId1"/>
  </sheets>
</workbook>
"""

WORKBOOK_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>
"""

SHARED_STRINGS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="9" uniqueCount="9">
  <si><t>2025 - 2026</t></si>
  <si><t>Name</t></si>
  <si><t>Unit Price</t></si>
  <si><t>P/FEE</t></si>
  <si><t>Jan</t></si>
  <si><t>Feb</t></si>
  <si><t>201 - Rafael Carlo Gutierrez</t></si>
  <si><t>PAID</t></si>
  <si><t></t></si>
</sst>
"""

SHEET_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    <row r="1">
      <c r="A1" t="s"><v>0</v></c>
    </row>
    <row r="3">
      <c r="A3" t="s"><v>1</v></c>
      <c r="B3" t="s"><v>2</v></c>
      <c r="C3" t="s"><v>3</v></c>
      <c r="D3" t="s"><v>4</v></c>
      <c r="E3" t="s"><v>5</v></c>
    </row>
    <row r="4">
      <c r="A4" t="s"><v>6</v></c>
      <c r="B4"><v>9951</v></c>
      <c r="C4"><v>2500</v></c>
      <c r="D4" t="s"><v>7</v></c>
      <c r="E4"></c>
    </row>
  </sheetData>
</worksheet>
"""


class ReverpointWorkbookImportTests(SimpleTestCase):
    def test_parse_sheet_billing_year_uses_end_year_by_default(self):
        self.assertEqual(parse_sheet_billing_year("2025 - 2026"), 2026)
        self.assertEqual(parse_sheet_billing_year("2025 - 2026", year_mode="start"), 2025)

    def test_normalize_person_name_is_unicode_safe_enough_for_spacing_and_punctuation(self):
        self.assertEqual(normalize_person_name(" Ma. Lucia delos Santo "), "MALUCIADELOSSANTO")
        self.assertEqual(normalize_person_name("张 伟"), "张伟")

    def test_infer_parking_slots_maps_exact_fee(self):
        self.assertEqual(infer_parking_slots(2500), (0, 1))
        self.assertEqual(infer_parking_slots(700), (2, 0))
        self.assertEqual(infer_parking_slots(2850), (1, 1))

    def test_parse_reverpoint_workbook_extracts_paid_months(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            workbook_path = Path(tmp_dir) / "reverpoint.xlsx"
            with ZipFile(workbook_path, "w") as archive:
                archive.writestr("[Content_Types].xml", CONTENT_TYPES)
                archive.writestr("_rels/.rels", ROOT_RELS)
                archive.writestr("xl/workbook.xml", WORKBOOK_XML)
                archive.writestr("xl/_rels/workbook.xml.rels", WORKBOOK_RELS)
                archive.writestr("xl/sharedStrings.xml", SHARED_STRINGS)
                archive.writestr("xl/worksheets/sheet1.xml", SHEET_XML)

            rows = parse_reverpoint_workbook(workbook_path)

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row.unit_number, "201")
        self.assertEqual(row.tenant_name, "Rafael Carlo Gutierrez")
        self.assertEqual(str(row.monthly_rent), "9951.00")
        self.assertEqual(str(row.parking_fee), "2500.00")
        self.assertEqual(row.billing_year, 2026)
        self.assertEqual(row.month_statuses[date(2026, 1, 1)], "PAID")
