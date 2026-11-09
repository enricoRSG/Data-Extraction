import json
from pathlib import Path
from io import BytesIO
import streamlit as st
import pandas as pd
from data_extraction.core import load, combine, prepare, workbook, export, batch, render_pdf_page

ROOT=Path(__file__).resolve().parent
st.set_page_config(page_title='Data Extraction | Enrico Raspa',page_icon='📄',layout='wide')
st.title('Data Extraction')
st.caption('Extract · Review · Convert | Enrico Raspa | v2.0')
st.write('Convert tabular documents into usable data, with explicit cleaning and source traceability.')
with st.sidebar:
    st.header('Import settings')
    separator=st.selectbox('CSV separator',[',',';','\t','|'])
    encoding=st.selectbox('CSV encoding',['utf-8-sig','cp1252'])
    pdf_header=st.checkbox('PDF: first table row contains headers',True)
    st.info('Local processing. Digital PDF tables with borders. No OCR. Max 25 MB per file, 100 PDF pages; batch max 20 files / 100 MB.')
    st.caption('Excel formatting and live formulas are not retained. Verify results against the source.')
load_options=dict(separator=separator,encoding=encoding,pdf_header=pdf_header)
mode=st.radio('Workflow',['Single file / merge tables','Batch conversion'],horizontal=True)
if mode=='Batch conversion':
    st.subheader('Convert multiple files')
    st.caption('Each sheet/table is exported separately. Tables are never merged automatically. All outcomes are listed in manifest.json.')
    files=st.file_uploader('Upload up to 20 files',type=['pdf','xlsx','csv','json'],accept_multiple_files=True)
    fmt=st.selectbox('Batch output format',['xlsx','csv','json'])
    trim=st.checkbox('Trim spaces',key='batch_trim')
    duplicates=st.checkbox('Remove duplicate rows',key='batch_dup')
    empty=st.checkbox('Remove empty rows',key='batch_empty')
    st.caption('Numeric conversion requires column review in the single-file workflow; batch preserves original values.')
    if files and st.button('Process batch'):
        try:
            archive,manifest=batch([(f.name,f.getvalue()) for f in files],fmt,load_options,dict(trim=trim,drop_duplicates=duplicates,drop_empty=empty))
            st.session_state['batch_result']=(archive,manifest)
        except Exception as exc: st.error(str(exc))
    if 'batch_result' in st.session_state:
        archive,manifest=st.session_state['batch_result']
        st.caption('Results of the most recently processed batch. Click Process batch after changing files or settings.')
        st.dataframe(pd.DataFrame(manifest),width='stretch')
        st.download_button('Download batch ZIP',archive,'data_extraction_batch.zip','application/zip')
    st.stop()

upload=st.file_uploader('Upload CSV, Excel, JSON or digital PDF',type=['csv','xlsx','json','pdf'])
examples={'Sales register':'sales_demo.pdf','Contacts':'contacts.pdf','Product price list':'products.pdf'}
if upload:
    payload,name=upload.getvalue(),upload.name
else:
    example=st.selectbox('Or explore a synthetic example',list(examples))
    name=examples[example]; payload=(ROOT/'examples'/name).read_bytes()
try: datasets=load(payload,name,**load_options)
except Exception as exc:
    st.error(f'Cannot import file: {exc}');st.stop()
chosen=st.selectbox('Choose a sheet or table',range(len(datasets)),format_func=lambda i:datasets[i].label)
ds=datasets[chosen]
if len(datasets)>1:
    merge=st.checkbox('Merge selected tables with matching headers')
    if merge:
        selected=st.multiselect('Tables to combine',range(len(datasets)),default=[chosen],format_func=lambda i:datasets[i].label)
        st.warning('Select only tables belonging to the same logical list. Matching columns alone do not prove that tables belong together. Each first row is treated as a header when the sidebar setting is enabled.')
        try: ds=combine([datasets[i] for i in selected])
        except ValueError as exc: st.error(str(exc));st.stop()
st.caption(f'Source: {ds.source} · {ds.location}')
left,right=st.columns(2)
with left:
    st.subheader('Original source')
    if name.lower().endswith('.pdf'):
        import pdfplumber
        with pdfplumber.open(BytesIO(payload)) as pdf: count=len(pdf.pages)
        page=st.number_input('PDF page',1,count,1)
        try: st.image(render_pdf_page(payload,int(page)-1),width='stretch')
        except Exception as exc: st.warning(f'Page preview unavailable: {exc}')
    else: st.dataframe(ds.frame,width='stretch')
with right:
    st.subheader('Extracted table')
    st.dataframe(ds.frame,width='stretch')
st.subheader('Review & prepare')
a,b,c=st.columns(3)
trim=a.checkbox('Trim surrounding spaces')
duplicates=b.checkbox('Remove duplicate rows')
empty=c.checkbox('Remove empty rows')
columns=st.multiselect('Columns to export',list(ds.frame.columns),default=list(ds.frame.columns))
numeric=st.multiselect('Convert these columns to numbers (leave IDs unselected)',columns)
locale=st.selectbox('Numeric format',['Italian','English'])
st.caption('Italian: 1.250,50 → 1250.50; 12,5% → 0.125. English: 1,250.50 → 1250.50. Invalid values remain text and are reported. Preview before downloading.')
if not columns: st.warning('Select at least one column.');st.stop()
try:
    frame,report=prepare(ds,trim,duplicates,empty,numeric,locale,columns)
except Exception as exc: st.error(str(exc));st.stop()
p=report['after']
a,b,c,d=st.columns(4)
for col,label,key in [(a,'Rows','rows'),(b,'Columns','columns'),(c,'Missing cells','missing_cells'),(d,'Duplicate rows','duplicate_rows')]: col.metric(label,p[key])
st.dataframe(frame,width='stretch')
if report['conversion_issues']:
    st.warning(f"{len(report['conversion_issues'])} numeric conversions need review. Original values retained.")
    st.dataframe(pd.DataFrame(report['conversion_issues']),width='stretch')
st.subheader('Data quality & descriptive analysis')
st.dataframe(pd.DataFrame(p['column_profile']),width='stretch')
st.caption('Duplicate removal compares all source columns before output column selection. Missing includes blanks. Numeric summaries do not infer the meaning of identifiers; only convert meaningful numeric fields.')
if len(frame) and len(frame.columns):
    category=st.selectbox('Frequency chart',list(frame.columns))
    st.bar_chart(frame[category].fillna('(missing)').astype(str).replace('', '(missing)').value_counts().head(10))
st.subheader('Download reviewed results')
fmt=st.selectbox('Output format',['xlsx','csv','json'])
if fmt=='csv': st.caption('CSV contains raw values. Import as text when formula-like strings must remain literal. XLSX writes strings as literal text.')
st.download_button('Download converted data',workbook(frame,report) if fmt=='xlsx' else export(frame,fmt),f'{Path(name).stem}_extracted.{fmt}')
st.caption('Excel includes Data, Quality, Columns, Audit, Provenance and Conversion issues sheets.')
st.download_button('Download audit JSON',json.dumps(report,indent=2,ensure_ascii=False).encode(),'quality_report.json','application/json')
