import os
import tempfile
import unittest
from pathlib import Path

from validator.document import Document, load_document, norm

FIX = Path(__file__).parent / "fixtures" / "requirements.md"


class LocateTests(unittest.TestCase):
    def setUp(self):
        self.doc = load_document(str(FIX))

    def test_norm_ignores_markup_case_yo_dashes(self):
        self.assertEqual(norm("**Ф-1.**  Задаёт «порог» — тут"), norm("ф-1. задает порог - тут"))

    def test_exact_with_markup_gives_line_and_section(self):
        loc = self.doc.locate("Держатель активной карты KZT задаёт целый порог")
        self.assertTrue(loc.exact)
        self.assertEqual(loc.section, "Функциональные требования")
        self.assertIn("Ф-1", self.doc.lines[loc.line - 1])

    def test_table_row_quote_with_cell_separators(self):
        loc = self.doc.locate("Покупка 31 января в 23:58 на 4 000 ₸ | Провести 1 февраля в 00:03 по Алматы")
        self.assertIsNotNone(loc)
        self.assertEqual(loc.section, "Критерии приемки")

    def test_fuzzy_match_tolerates_small_typo(self):
        loc = self.doc.locate("Месяц определяется по дате совершения покупки в Алмате.")
        self.assertIsNotNone(loc)
        self.assertFalse(loc.exact)

    def test_invented_quote_not_found(self):
        self.assertIsNone(self.doc.locate("Система обязана отправлять SMS при каждом входе"))

    def test_too_short_quote_rejected(self):
        self.assertIsNone(self.doc.locate("ab"))

    def test_chunks_split_on_headings_for_long_text(self):
        text = "\n".join(f"## Раздел {i}\n" + "слово " * 300 for i in range(20))
        parts = Document(text).chunks(max_chars=5000)
        self.assertGreater(len(parts), 1)
        self.assertEqual("\n".join(parts).count("## Раздел"), 20)


class LoadTests(unittest.TestCase):
    def test_unsupported_and_missing_and_empty(self):
        with tempfile.TemporaryDirectory() as d:
            bad, empty = Path(d, "a.xyz"), Path(d, "e.md")
            bad.write_text("x"), empty.write_text("  \n")
            with self.assertRaises(ValueError):
                load_document(str(bad))
            with self.assertRaises(ValueError):
                load_document(str(empty))
            with self.assertRaises(FileNotFoundError):
                load_document(str(Path(d, "none.md")))

    def test_pdf_with_table_and_page_markers(self):
        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.pdfbase import pdfmetrics
            from reportlab.pdfbase.ttfonts import TTFont
            from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle
            from reportlab.lib.styles import getSampleStyleSheet
            from reportlab.lib import colors
        except ImportError:
            self.skipTest("reportlab не установлен")
        font = next((p for p in ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                                 "/usr/share/fonts/dejavu/DejaVuSans.ttf"] if os.path.exists(p)), None)
        if not font:
            self.skipTest("нет шрифта с кириллицей")
        pdfmetrics.registerFont(TTFont("DJ", font))
        st = getSampleStyleSheet()["Normal"]
        st.fontName = "DJ"
        with tempfile.TemporaryDirectory() as d:
            path = str(Path(d, "t.pdf"))
            tbl = Table([["Поле", "Значение"], ["Метод", "GET"], ["Адрес", "/alerts/saveLimit"]])
            tbl.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.black), ("FONTNAME", (0, 0), (-1, -1), "DJ")]))
            SimpleDocTemplate(path, pagesize=A4).build([Paragraph("Требование Ф-1: система должна сохранять порог.", st), tbl])
            doc = load_document(path)
        self.assertIn("<!-- стр. 1 -->", doc.text)
        self.assertIn("Ф-1", doc.text)
        self.assertIn("| Метод | GET |", doc.text)
        self.assertEqual(doc.locate("система должна сохранять порог").page, 1)

    def test_docx_headings_and_tables(self):
        try:
            import docx
        except ImportError:
            self.skipTest("python-docx не установлен")
        with tempfile.TemporaryDirectory() as d:
            path = str(Path(d, "t.docx"))
            dd = docx.Document()
            dd.add_heading("Цели", level=2)
            dd.add_paragraph("Клиент узнаёт о достижении бюджета.")
            t = dd.add_table(rows=2, cols=2)
            t.cell(0, 0).text, t.cell(0, 1).text, t.cell(1, 0).text, t.cell(1, 1).text = "Поле", "Значение", "Код", "200"
            dd.save(path)
            doc = load_document(path)
        self.assertIn("## Цели", doc.text)
        self.assertIn("| Код | 200 |", doc.text)


if __name__ == "__main__":
    unittest.main()
