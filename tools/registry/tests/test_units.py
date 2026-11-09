"""IMP2-05 - units of a source (text lines, ODS paragraphs): lossless, addressable, explicit about what it cannot read."""
import io
import unittest
import zipfile

from clxreg import units

NS = ('xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
      'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" xmlns:dc="http://purl.org/dc/elements/1.1/" '
      'xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0"')


def ods(sheets):
    """sheets: {name: rows_xml}"""
    body = "".join(f'<table:table table:name="{n}">{r}</table:table>' for n, r in sheets.items())
    xml = (f'<?xml version="1.0" encoding="UTF-8"?><office:document-content {NS}><office:body><office:spreadsheet>{body}'
           f'</office:spreadsheet></office:body></office:document-content>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("mimetype", "application/vnd.oasis.opendocument.spreadsheet")
        z.writestr("content.xml", xml.encode("utf-8"))
    return buf.getvalue()


def cell(inner="", **attrs):
    a = "".join(f' table:{k.replace("_", "-")}="{v}"' for k, v in attrs.items())
    return f"<table:table-cell{a}>{inner}</table:table-cell>"


def row(*cells, **attrs):
    a = "".join(f' table:{k.replace("_", "-")}="{v}"' for k, v in attrs.items())
    return f"<table:table-row{a}>{''.join(cells)}</table:table-row>"


def p(text):
    return f"<text:p>{text}</text:p>"


def ids(us):
    return [(u.id, u.text) for u in us]


class TextUnitTests(unittest.TestCase):
    def test_lines_are_split_at_lf_only_and_numbered_from_one(self):
        us = units.read_units(".md", b"a\nb\n\nc")
        self.assertEqual(ids(us), [("L1", "a"), ("L2", "b"), ("L3", ""), ("L4", "c")])
        self.assertEqual([u.line for u in us], [1, 2, 3, 4])

    def test_trailing_newline_gives_a_final_empty_unit(self):
        self.assertEqual(ids(units.read_units(".txt", b"a\n")), [("L1", "a"), ("L2", "")])

    def test_empty_file_is_one_empty_line(self):
        self.assertEqual(ids(units.read_units(".md", b"")), [("L1", "")])

    def test_other_line_separators_do_not_split(self):
        text = "a b\x0bc\x0cd\x85e".encode("utf-8")
        self.assertEqual(ids(units.read_units(".md", text)), [("L1", "a b\x0bc\x0cd\x85e")])

    def test_crlf_and_bom_are_kept_verbatim(self):
        us = units.read_units(".md", b"\xef\xbb\xbfRT1\r\nx\r\n")
        self.assertEqual([u.text for u in us], ["﻿RT1\r", "x\r", ""])

    def test_the_text_is_never_normalised(self):
        raw = "  \tRT1  –  RT3   ř  "
        self.assertEqual(units.read_units(".md", raw.encode("utf-8"))[0].text, raw)

    def test_supported_suffixes_are_case_insensitive(self):
        for s in (".md", ".MD", ".txt", ".json", ".py", ".sdoc", ".cs", ".yml", ".yaml", ".diff"):
            self.assertEqual(len(units.read_units(s, b"x")), 1, s)

    def test_unsupported_suffix_is_explicit(self):
        for s in (".docx", ".zip", "", ".bin", ".pdf"):
            with self.subTest(s):
                with self.assertRaises(units.UnsupportedSource) as cm:
                    units.read_units(s, b"x")
                self.assertTrue(str(cm.exception))

    def test_invalid_utf8_is_unsupported_not_replaced(self):
        for raw in (b"\xff\xfe", b"ab\x80cd"):
            with self.assertRaises(units.UnsupportedSource):
                units.read_units(".md", raw)

    def test_suffix_of_handles_both_path_separators(self):
        self.assertEqual(units.suffix_of("dir\\f.MD"), ".MD")
        self.assertEqual(units.suffix_of("a/b/f.ods"), ".ods")
        self.assertEqual(units.suffix_of("noext"), "")
        self.assertEqual(units.suffix_of("a.dir\\file"), "")

    def test_unit_ids_map_back_to_lines(self):
        us = units.read_units(".md", b"x\ny\nz")
        self.assertEqual(units.find_unit(us, "L2").text, "y")
        self.assertIsNone(units.find_unit(us, "L9"))


class OdsUnitTests(unittest.TestCase):
    def read(self, sheets):
        return units.read_units(".ods", ods(sheets))

    def test_cells_are_addressed_by_sheet_row_column_and_paragraph(self):
        us = self.read({"S1": row(cell(p("a")), cell(p("b"))) + row(cell(), cell(p("c")))})
        self.assertEqual(ids(us), [("S1!R1C1/p1", "a"), ("S1!R1C2/p1", "b"), ("S1!R2C2/p1", "c")])
        self.assertTrue(all(u.line is None for u in us))

    def test_two_paragraphs_are_two_units(self):
        us = self.read({"S": row(cell(p("x") + p("y")))})
        self.assertEqual(ids(us), [("S!R1C1/p1", "x"), ("S!R1C1/p2", "y")])

    def test_repeated_empty_columns_and_rows_only_move_the_address(self):
        us = self.read({"S": row(cell(number_columns_repeated="3"), cell(p("x")), number_rows_repeated="2") + row(cell(p("y")))})
        self.assertEqual(ids(us), [("S!R1C4/p1", "x"), ("S!R2C4/p1", "x"), ("S!R3C1/p1", "y")])

    def test_repeated_non_empty_cells_are_emitted_for_every_repetition(self):
        us = self.read({"S": row(cell(p("x"), number_columns_repeated="2"), number_rows_repeated="2")})
        self.assertEqual([i for i, _ in ids(us)], ["S!R1C1/p1", "S!R1C2/p1", "S!R2C1/p1", "S!R2C2/p1"])
        self.assertEqual({t for _, t in ids(us)}, {"x"})

    def test_a_huge_repetition_of_text_is_refused_not_truncated(self):
        with self.assertRaises(units.UnsupportedSource):
            self.read({"S": row(cell(p("x"), number_columns_repeated="100000"))})

    def test_spaces_tabs_line_breaks_spans_and_links_keep_the_literal_text(self):
        inner = ('<text:p>a<text:s text:c="3"/>b<text:tab/>c<text:line-break/>d<text:span>e</text:span>f'
                 '<text:a xlink:href="u" xmlns:xlink="http://www.w3.org/1999/xlink">g<text:span>h</text:span></text:a>i</text:p>')
        us = self.read({"S": row(cell(inner))})
        self.assertEqual(us[0].text, "a   b\tc\ndefghi")

    def test_a_single_space_element_defaults_to_one_space(self):
        us = self.read({"S": row(cell("<text:p>a<text:s/>b</text:p>"))})
        self.assertEqual(us[0].text, "a b")

    def test_annotations_are_their_own_units_and_not_merged_into_the_cell(self):
        note = '<office:annotation><dc:creator>Someone</dc:creator><dc:date>2026-01-01</dc:date><text:p>note RT1</text:p></office:annotation>'
        us = self.read({"S": row(cell(note + p("main")))})
        self.assertEqual(ids(us), [("S!R1C1/n1p1", "note RT1"), ("S!R1C1/p1", "main")])

    def test_unknown_content_in_an_annotation_is_unsupported(self):
        for child in ("<draw:frame><text:p>hidden</text:p></draw:frame>", "<draw:frame>plain text</draw:frame>", "<text:soft-page-break/>"):
            note = f'<office:annotation>{child}<text:p>shown</text:p></office:annotation>'
            with self.subTest(child):
                with self.assertRaises(units.UnsupportedSource):
                    self.read({"S": row(cell(note))})

    def test_covered_cells_advance_the_column_and_carry_no_text(self):
        covered = '<table:covered-table-cell table:number-columns-repeated="2"/>'
        us = self.read({"S": row(cell(p("a")), covered, cell(p("b")))})
        self.assertEqual([i for i, _ in ids(us)], ["S!R1C1/p1", "S!R1C4/p1"])

    def test_empty_paragraphs_are_not_units(self):
        self.assertEqual(self.read({"S": row(cell(p("")))}), [])

    def test_unknown_content_in_a_cell_is_unsupported_not_skipped(self):
        for inner in ('<draw:frame><draw:text-box><text:p>hidden</text:p></draw:text-box></draw:frame>',
                      '<text:list><text:list-item><text:p>x</text:p></text:list-item></text:list>',
                      '<text:p>a<text:note><text:note-body><text:p>fn</text:p></text:note-body></text:note>b</text:p>'):
            with self.subTest(inner[:30]):
                with self.assertRaises(units.UnsupportedSource):
                    self.read({"S": row(cell(inner))})

    def test_sheets_are_read_in_document_order(self):
        us = self.read({"B": row(cell(p("1"))), "A": row(cell(p("2")))})
        self.assertEqual([u.id for u in us], ["B!R1C1/p1", "A!R1C1/p1"])

    def test_broken_containers_are_unsupported(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("other.xml", "x")
        for data in (b"PK", b"not a zip", buf.getvalue()):
            with self.subTest(data[:6]):
                with self.assertRaises(units.UnsupportedSource):
                    units.read_units(".ods", data)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("content.xml", "<not-closed>")
        with self.assertRaises(units.UnsupportedSource):
            units.read_units(".ods", buf.getvalue())

    def test_bad_repetition_counts_are_unsupported(self):
        for bad in ("0", "-1", "x", ""):
            with self.subTest(bad):
                with self.assertRaises(units.UnsupportedSource):
                    self.read({"S": row(cell(p("a"), number_columns_repeated=bad))})
                with self.assertRaises(units.UnsupportedSource):
                    self.read({"S": row(cell(p("a")), number_rows_repeated=bad)})

    def test_a_document_without_a_spreadsheet_body_is_unsupported(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("content.xml", f'<office:document-content {NS}><office:body/></office:document-content>')
        with self.assertRaises(units.UnsupportedSource):
            units.read_units(".ods", buf.getvalue())
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("content.xml", f'<office:document-content {NS}/>')
        with self.assertRaises(units.UnsupportedSource):
            units.read_units(".ods", buf.getvalue())

    def test_the_cap_applies_to_the_product_of_row_and_column_repetition(self):
        self.read({"S": row(cell(p("x"), number_columns_repeated="100"), number_rows_repeated="100")})
        with self.assertRaises(units.UnsupportedSource):
            self.read({"S": row(cell(p("x"), number_columns_repeated="101"), number_rows_repeated="100")})

    def test_headings_are_paragraph_units(self):
        us = self.read({"S": row(cell("<text:h>Title</text:h>"))})
        self.assertEqual(ids(us), [("S!R1C1/p1", "Title")])

    def test_rows_inside_groups_keep_their_numbering(self):
        grouped = f"<table:table-header-rows>{row(cell(p('h')))}</table:table-header-rows>{row(cell(p('b')))}"
        us = self.read({"S": grouped})
        self.assertEqual([i for i, _ in ids(us)], ["S!R1C1/p1", "S!R2C1/p1"])


if __name__ == "__main__":
    unittest.main()
