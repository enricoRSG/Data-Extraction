import unittest
from pathlib import Path
import os
from streamlit.testing.v1 import AppTest
class AppTests(unittest.TestCase):
    def test_demo_and_cleaning(self):
        previous = os.getcwd()
        try:
            os.chdir(Path(__file__).resolve().parents[1])
            app = AppTest.from_file(str(Path.cwd() / 'app.py')).run(timeout=30)
            self.assertFalse(app.exception)
            self.assertEqual([x.value for x in app.metric], ['7','4','1','1'])
            next(x for x in app.checkbox if x.label == 'Remove duplicate rows').check().run()
            self.assertFalse(app.exception)
            self.assertEqual([x.value for x in app.metric], ['6','4','1','0'])
        finally:
            os.chdir(previous)

    def test_numeric_preview(self):
        root=Path(__file__).resolve().parents[1]
        app=AppTest.from_file(str(root/'app.py')).run(timeout=30)
        next(x for x in app.selectbox if x.label=='Or explore a synthetic example').select('Product price list').run()
        next(x for x in app.multiselect if x.label.startswith('Convert these')).select('Price EUR').select('Discount').run()
        self.assertFalse(app.exception)
        self.assertEqual([x.value for x in app.metric],['3','4','0','0'])

    def test_batch_screen(self):
        root=Path(__file__).resolve().parents[1]
        app=AppTest.from_file(str(root/'app.py')).run(timeout=30)
        app.radio[0].set_value('Batch conversion').run()
        self.assertFalse(app.exception)
        self.assertTrue(any(x.value=='Convert multiple files' for x in app.subheader))
