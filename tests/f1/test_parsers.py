from __future__ import annotations

from unittest.mock import patch

from medicafe_v1.sources.domain import CommandError
from medicafe_v1.sources.parsers import MAX_ROWS, parse_csv, parse_docx

from tests.fixtures.synthetic_inputs import CSV_HEADER, csv_bytes, docx_bytes, empty_docx_bytes, synthetic_rows
from tests.f1.base import F1TestCase


class ParserValidationTests(F1TestCase):
    def test_csv_bom_preserves_raw_values_normalizes_and_warns(self):
        rows = [
            {"row_id": " duplicate ", "patient_ref": " 000042 ", "service_date": " 2026-01-15 ", "note": " note one "},
            {"row_id": "duplicate", "patient_ref": "   ", "service_date": "not-a-date", "note": " note two "},
        ]
        parsed = parse_csv(csv_bytes(rows, bom=True))

        self.assertEqual(len(parsed), 2)
        self.assertEqual(parsed[0].raw_values["patient_ref"], " 000042 ")
        self.assertEqual(parsed[0].normalized_values["patient_ref"], "000042")
        self.assertEqual(parsed[0].source_locator, {"format": "csv", "data_row": 1})
        self.assertIn("duplicate_row_id", parsed[0].warnings)
        self.assertIn("duplicate_row_id", parsed[1].warnings)
        self.assertIn("patient_ref_blank", parsed[1].warnings)
        self.assertIn("service_date_invalid", parsed[1].warnings)

    def test_csv_rejects_encoding_header_columns_and_row_limit(self):
        with self.assertRaises(CommandError) as not_utf8:
            parse_csv(b"\xff\xfe")
        self.assertEqual(not_utf8.exception.reason_code, "csv_not_utf8")

        with self.assertRaises(CommandError) as wrong_header:
            parse_csv(csv_bytes(header=("row_id", "patient", "service_date", "note")))
        self.assertEqual(wrong_header.exception.reason_code, "invalid_header")

        with self.assertRaises(CommandError) as wrong_columns:
            parse_csv(b"row_id,patient_ref,service_date,note\nrow-1,000042,2026-01-15,note,extra\n")
        self.assertEqual(wrong_columns.exception.reason_code, "invalid_column_count")

        rows = synthetic_rows()
        rows.extend({"row_id": f"row-{index:04d}", "patient_ref": "000042", "service_date": "2026-01-15", "note": "synthetic"}
                    for index in range(2, MAX_ROWS + 2))
        with self.assertRaises(CommandError) as too_many:
            parse_csv(csv_bytes(rows))
        self.assertEqual(too_many.exception.reason_code, "row_limit_exceeded")

    def test_docx_table_rows_preserve_locator_and_validate_shape(self):
        parsed = parse_docx(docx_bytes(synthetic_rows(note="SYNTHETIC_DOCX_SENTINEL")))
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0].raw_values["note"], "SYNTHETIC_DOCX_SENTINEL")
        self.assertEqual(parsed[0].source_locator, {"format": "docx", "table": 1, "table_row": 2})

        warned = parse_docx(docx_bytes(synthetic_rows(patient_ref=" ", service_date="bad")))
        self.assertIn("patient_ref_blank", warned[0].warnings)
        self.assertIn("service_date_invalid", warned[0].warnings)

        with self.assertRaises(CommandError) as malformed:
            parse_docx(b"not a zip archive")
        self.assertEqual(malformed.exception.reason_code, "docx_malformed")

        with self.assertRaises(CommandError) as no_table:
            parse_docx(empty_docx_bytes())
        self.assertEqual(no_table.exception.reason_code, "docx_table_shape_unsupported")

        with self.assertRaises(CommandError) as multiple_tables:
            parse_docx(docx_bytes(table_count=2))
        self.assertEqual(multiple_tables.exception.reason_code, "docx_table_shape_unsupported")

        with self.assertRaises(CommandError) as invalid_header:
            parse_docx(docx_bytes(header=("row_id", "patient_ref", "wrong_date", "note")))
        self.assertEqual(invalid_header.exception.reason_code, "invalid_header")

    def test_docx_expanded_zip_limit_is_fail_closed(self):
        with patch("medicafe_v1.sources.parsers.MAX_DOCX_EXPANDED", 1):
            with self.assertRaises(CommandError) as expanded:
                parse_docx(docx_bytes())
        self.assertEqual(expanded.exception.reason_code, "docx_expanded_limit_exceeded")
