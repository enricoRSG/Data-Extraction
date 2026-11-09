import unittest
from pathlib import Path
from io import BytesIO
import json
import pandas as pd
from data_extraction.core import load, clean, profile, export, audit, headers
ROOT = Path(__file__).resolve().parents[1]
class CoreTests(unittest.TestCase):
    def test_csv_identifiers(self):
        d = load(b'id,name\n001,Alice\n002,NA\n', 'test.csv')[0]
        self.assertEqual(d.frame.iloc[0,0], '001')
        self.assertEqual(d.frame.iloc[1,1], 'NA')
    def test_semicolon_encoding(self):
        d = load('id;name\n001;città\n'.encode('cp1252'), 'x.csv', ';', 'cp1252')[0]
        self.assertEqual(d.frame.iloc[0,1], 'città')
    def test_clean_does_not_mutate(self):
        f = pd.DataFrame({'a':[' x ', 'x', ' '], 'n':['2','2','']})
        out = clean(f, True, True, True)
        self.assertEqual(len(out), 1)
        self.assertEqual(f.iloc[0,0], ' x ')
    def test_profile(self):
        p = profile(pd.DataFrame({'x':['1','3',''], 'y':[' a ',' ',None]}))
        self.assertEqual(p['missing_cells'], 3)
        self.assertEqual(p['column_profile'][0]['mean'], 2)
    def test_pdf_and_reference(self):
        ds = load((ROOT/'examples/sales_demo.pdf').read_bytes(), 'sales_demo.pdf')[0]
        self.assertEqual(len(ds.frame), 7)
        out = clean(ds.frame, True, True, True)
        self.assertEqual(len(out), 6)
        self.assertEqual(profile(out)['missing_cells'], 1)
        self.assertEqual(profile(out)['column_profile'][-1]['sum'], 2850)
        expected = pd.read_excel(ROOT/'examples/expected_sales.xlsx', dtype=str, keep_default_na=False)
        pd.testing.assert_frame_equal(out.fillna(''), expected)
        self.assertEqual(len(audit(ds, out, {})['source_sha256']), 64)
    def test_exports(self):
        f = pd.DataFrame({'id':['001','002'], 'name':['Alice','Béa']})
        for fmt in ['csv','xlsx','json']:
            pd.testing.assert_frame_equal(load(export(f,fmt),'x.'+fmt)[0].frame, f)
    def test_xlsx_formula_is_literal(self):
        from openpyxl import load_workbook
        book = load_workbook(BytesIO(export(pd.DataFrame({'x':['=1+1']}), 'xlsx')))
        self.assertEqual(book.active['A2'].data_type, 's')
    def test_multiple_sheets(self):
        buf=BytesIO()
        with pd.ExcelWriter(buf, engine='openpyxl') as w:
            pd.DataFrame({'a':['001']}).to_excel(w,sheet_name='One',index=False)
            pd.DataFrame({'b':['two']}).to_excel(w,sheet_name='Two',index=False)
        self.assertEqual(len(load(buf.getvalue(),'x.xlsx')), 2)
    def test_bad_inputs(self):
        for data, name in [(b'', 'x.csv'), (b'abc','x.txt'), (b'{"x":1}','x.json'),(b'[{"x":[]}]','x.json')]:
            with self.assertRaises(ValueError): load(data,name)
    def test_headers(self):
        self.assertEqual(len(set(headers(['A','A','A_2',None]))), 4)
    def test_pdf_without_tables(self):
        from reportlab.pdfgen import canvas
        out=BytesIO(); c=canvas.Canvas(out); c.drawString(72,720,'No table'); c.save()
        with self.assertRaisesRegex(ValueError,'No ruled'): load(out.getvalue(),'plain.pdf')
if __name__ == '__main__': unittest.main()
