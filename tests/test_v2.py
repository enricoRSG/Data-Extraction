import unittest,json
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile
import pandas as pd
from openpyxl import load_workbook
from data_extraction.core import *
ROOT=Path(__file__).resolve().parents[1]
class V2Tests(unittest.TestCase):
    def test_italian(self):
        for text,value in [('1.250,50',1250.5),('€ 1.250,50',1250.5),('12,5%',.125),('(250,00)',-250),('-1.250,50',-1250.5),('1.250,50 EUR',1250.5)]:
            self.assertAlmostEqual(parse_number(text),value)
    def test_english(self):
        self.assertEqual(parse_number('$ 1,250.50','English'),1250.5)
        self.assertEqual(parse_number('10%','English'),.1)
    def test_invalid(self):
        for text in ['1,250.50','12.34,56','abc','NaN','inf','--2','(-2)']:
            with self.assertRaises(ValueError):parse_number(text)
    def test_preserve_invalid_and_ids(self):
        ds=load(b'id;amount\n001;1.250,50\n002;wrong\n','x.csv',';')[0]
        f,r=prepare(ds,numeric_columns=['amount'])
        self.assertEqual(f.iloc[0,0],'001');self.assertEqual(f.iloc[0,1],1250.5)
        self.assertEqual(f.iloc[1,1],'wrong');self.assertEqual(len(r['conversion_issues']),1)
        self.assertNotIn('sum',r['after']['column_profile'][1])
    def test_merge_pdf_and_provenance(self):
        datasets=load((ROOT/'examples/sales_multipage.pdf').read_bytes(),'x.pdf')
        ds=combine(datasets);f,r=prepare(ds,numeric_columns=['Amount EUR'])
        self.assertEqual(len(f),4)
        self.assertEqual(f['Amount EUR'].sum(),2750.5)
        self.assertIn('Page 2',r['provenance'][2]['location'])
    def test_different_schema(self):
        with self.assertRaisesRegex(ValueError,'different columns'):
            combine([Dataset('a',pd.DataFrame({'a':['x']}),'x','1','1'),Dataset('b',pd.DataFrame({'b':['x']}),'x','1','2')])
    def test_repeated_header(self):
        ds=Dataset('a',pd.DataFrame({'ID':['001','ID','002'],'X':['a','X','b']}),'x','1','1')
        merged=combine([ds]);self.assertEqual(len(merged.frame),2)
        self.assertEqual(merged.repeated_headers_removed,1)
        f,r=prepare(merged);self.assertEqual(r['provenance'][1]['source_data_row'],3)
    def test_provenance_after_clean(self):
        ds=load(b'id,n\n001,2\n001,2\n002,3\n','x.csv')[0]
        f,r=prepare(ds,drop_duplicates=True,selected_columns=['id'])
        self.assertEqual([p['source_data_row'] for p in r['provenance']],[1,3])
    def test_workbook(self):
        ds=load(b'id,n\n001,2\n002,3\n','x.csv')[0];f,r=prepare(ds,numeric_columns=['n'])
        wb=load_workbook(BytesIO(workbook(f,r)))
        self.assertEqual(wb.sheetnames,['Data','Quality','Columns','Audit','Provenance','Conversion issues'])
        self.assertEqual(wb['Data']['A2'].value,'001')
        self.assertEqual(wb['Data']['B2'].data_type,'n')
    def test_batch_mixed_errors_and_collisions(self):
        output,manifest=batch([('same.csv',b'a\nx\n'),('same.csv',b'a\ny\n'),('bad.pdf',b'bad')])
        self.assertEqual([m['status'] for m in manifest],['success','success','failed'])
        with ZipFile(BytesIO(output)) as z:
            names=z.namelist();self.assertEqual(len(names),len(set(names)))
            self.assertEqual(len(json.loads(z.read('manifest.json'))),3)
    def test_batch_limits(self):
        with self.assertRaises(ValueError):batch([('x',b'x')]*21)
    def test_pdf_preview(self):
        im=render_pdf_page((ROOT/'examples/products.pdf').read_bytes(),0)
        self.assertGreater(im.width,500)
