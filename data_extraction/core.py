from dataclasses import dataclass
from io import BytesIO, StringIO
import hashlib
import json
from pathlib import Path
import pandas as pd
import pdfplumber

MAX_BYTES = 25 * 1024 * 1024

@dataclass
class Dataset:
    label: str
    frame: pd.DataFrame
    source: str
    sha256: str
    location: str

def headers(values):
    """Keep every column, including blank and repeated PDF headers."""
    result, used = [], set()
    for i, value in enumerate(values):
        base = str(value).strip() if value is not None and str(value).strip() else f'column_{i+1}'
        name, suffix = base, 2
        while name in used:
            name = f'{base}_{suffix}'
            suffix += 1
        used.add(name)
        result.append(name)
    return result

def load(data: bytes, filename: str, separator=',', encoding='utf-8-sig', pdf_header=True):
    if not data or len(data) > MAX_BYTES:
        raise ValueError('Choose a non-empty file smaller than 25 MB.')
    digest = hashlib.sha256(data).hexdigest()
    suffix = Path(filename).suffix.lower()
    frames = []
    if suffix == '.csv':
        frame = pd.read_csv(BytesIO(data), sep=separator, encoding=encoding, dtype=str, keep_default_na=False)
        frames.append(('CSV', frame, 'CSV rows'))
    elif suffix == '.xlsx':
        # Read textual values as stored; identifiers such as 001 remain text.
        sheets = pd.read_excel(BytesIO(data), sheet_name=None, dtype=str, keep_default_na=False, engine='openpyxl')
        frames.extend((name, frame, f'Sheet: {name}') for name, frame in sheets.items())
    elif suffix == '.json':
        records = json.loads(data.decode('utf-8-sig'))
        if not isinstance(records, list) or any(not isinstance(row, dict) for row in records):
            raise ValueError('JSON must contain an array of flat record objects.')
        if any(isinstance(v, (dict, list)) for row in records for v in row.values()):
            raise ValueError('Nested JSON is outside this version; provide flat records.')
        frames.append(('JSON', pd.DataFrame(records), 'JSON records'))
    elif suffix == '.pdf':
        with pdfplumber.open(BytesIO(data)) as pdf:
            if len(pdf.pages) > 100:
                raise ValueError('PDF limit: 100 pages.')
            for page_number, page in enumerate(pdf.pages, 1):
                for table_number, table in enumerate(page.extract_tables(), 1):
                    if not table:
                        continue
                    width = max(len(row) for row in table)
                    table = [row + [None] * (width-len(row)) for row in table]
                    columns = headers(table[0]) if pdf_header else headers([None]*width)
                    frame = pd.DataFrame(table[1:] if pdf_header else table, columns=columns)
                    location = f'Page {page_number}, table {table_number}'
                    frames.append((location, frame, location))
        if not frames:
            raise ValueError('No ruled tables detected. Scans, OCR and borderless layouts are not supported in v1.')
    else:
        raise ValueError('Supported input: .csv, .xlsx, .json, .pdf')
    return [Dataset(label, frame, filename, digest, location) for label, frame, location in frames]

def profile(frame):
    empty = frame.isna() | frame.apply(lambda col: col.map(lambda v: isinstance(v, str) and not v.strip()))
    columns = []
    for name in frame.columns:
        col = frame[name]
        nonempty = col[~empty[name]]
        numeric = pd.to_numeric(nonempty, errors='coerce')
        item = {'column': str(name), 'missing': int(empty[name].sum()), 'unique_nonempty': int(nonempty.nunique()), 'numeric_count': int(numeric.notna().sum())}
        if len(nonempty) and numeric.notna().all():
            item.update(min=float(numeric.min()), max=float(numeric.max()), mean=float(numeric.mean()), sum=float(numeric.sum()))
        columns.append(item)
    return {'rows': len(frame), 'columns': len(frame.columns), 'duplicate_rows': int(frame.duplicated().sum()), 'missing_cells': int(empty.sum().sum()), 'column_profile': columns}

def clean(frame, trim=False, drop_duplicates=False, drop_empty=False):
    out = frame.copy()
    if trim:
        out = out.apply(lambda col: col.map(lambda v: v.strip() if isinstance(v, str) else v))
    if drop_empty:
        blank = out.isna() | out.apply(lambda col: col.map(lambda v: isinstance(v, str) and not v.strip()))
        out = out.loc[~blank.all(axis=1)]
    if drop_duplicates:
        out = out.drop_duplicates()
    return out.reset_index(drop=True)

def export(frame, fmt):
    if fmt == 'csv':
        return frame.to_csv(index=False).encode('utf-8-sig')
    if fmt == 'json':
        return frame.to_json(orient='records', force_ascii=False, indent=2).encode('utf-8')
    if fmt == 'xlsx':
        out = BytesIO()
        with pd.ExcelWriter(out, engine='openpyxl') as writer:
            frame.to_excel(writer, sheet_name='Data', index=False)
            # Force strings to remain literal, including values starting with '='.
            for row in writer.book['Data']:
                for cell in row:
                    if isinstance(cell.value, str):
                        cell.data_type = 's'
        return out.getvalue()
    raise ValueError('Output must be csv, xlsx or json.')

def audit(dataset, frame, operations):
    return {'source_file': dataset.source, 'source_sha256': dataset.sha256, 'source_location': dataset.location,
            'operations': operations, 'before': profile(dataset.frame), 'after': profile(frame),
            'notes': ['Missing includes empty or whitespace-only cells.', 'Numeric summaries use dot decimal notation; text is never silently converted.', 'PDF extraction must be checked against the source.']}

# v2: explicit transformations and row-level traceability.
import re
from decimal import Decimal, InvalidOperation
from zipfile import ZipFile, ZIP_DEFLATED

def parse_number(value, locale='Italian'):
    """Strict locale parsing. Percentages are fractions; ambiguous values fail closed."""
    if value is None or (isinstance(value, str) and not value.strip()) or pd.isna(value):
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if not __import__('math').isfinite(value):
            raise ValueError('Non-finite value')
        return value
    raw = str(value).strip().replace('\u00a0', ' ')
    percent = raw.endswith('%')
    if percent:
        raw = raw[:-1].strip()
    raw = re.sub(r'^(?:€|EUR|\$|USD)\s*|\s*(?:€|EUR|\$|USD)$', '', raw).strip()
    negative = raw.startswith('(') and raw.endswith(')')
    if negative:
        raw = raw[1:-1]
    decimal, thousand = (',', '.') if locale == 'Italian' else ('.', ',')
    pattern = rf'[+-]?(?:\d{{1,3}}(?:{re.escape(thousand)}\d{{3}})+|\d+)(?:{re.escape(decimal)}\d+)?'
    if not re.fullmatch(pattern, raw):
        raise ValueError(f'Invalid {locale} numeric value')
    number = Decimal(raw.replace(thousand, '').replace(decimal, '.'))
    if negative:
        if number < 0 or raw.startswith('+'):
            raise ValueError('Ambiguous sign')
        number = -number
    if percent:
        number /= 100
    if not number.is_finite() or abs(number) > Decimal('1e15'):
        raise ValueError('Number outside supported precision/range')
    return float(number)

def combine(datasets):
    """Merge only explicitly selected tables with identical trimmed headers."""
    if not datasets:
        raise ValueError('Select at least one table.')
    schema = [str(c).strip() for c in datasets[0].frame.columns]
    if len(set(schema)) != len(schema):
        raise ValueError('Ambiguous duplicate headers.')
    frames, origins, dropped = [], [], 0
    for ds in datasets:
        if [str(c).strip() for c in ds.frame.columns] != schema:
            raise ValueError('Selected tables have different columns. Merge cancelled.')
        f = ds.frame.copy(); f.columns = schema
        keep = ~f.apply(lambda row: [str(v).strip() for v in row] == schema, axis=1)
        dropped += int((~keep).sum())
        frames.append(f.loc[keep])
        existing = getattr(ds, 'origins', None)
        for i in f.index[keep]:
            origins.append(existing[i] if existing else {'source_file':ds.source, 'sha256':ds.sha256, 'location':ds.location, 'source_data_row':int(i)+1})
    result = Dataset('Merged tables', pd.concat(frames, ignore_index=True), '; '.join(dict.fromkeys(d.source for d in datasets)),
                     '; '.join(dict.fromkeys(d.sha256 for d in datasets)), '; '.join(d.location for d in datasets))
    result.origins = origins
    result.repeated_headers_removed = dropped
    return result

def prepare(dataset, trim=False, drop_duplicates=False, drop_empty=False, numeric_columns=None, locale='Italian', selected_columns=None):
    numeric_columns = numeric_columns or []
    f = dataset.frame.copy()
    if trim:
        f = f.apply(lambda col: col.map(lambda v: v.strip() if isinstance(v,str) else v))
    if drop_empty:
        blank = f.isna() | f.apply(lambda col: col.map(lambda v: isinstance(v,str) and not v.strip()))
        f = f.loc[~blank.all(axis=1)]
    issues = []
    for name in numeric_columns:
        converted = []
        for i, value in f[name].items():
            try:
                converted.append(parse_number(value, locale))
            except (ValueError, InvalidOperation):
                converted.append(value)
                issues.append({'source_data_row':int(i)+1,'column':str(name),'original_value':str(value), 'reason':'Invalid number: original text retained'})
        f[name] = pd.Series(converted, index=f.index, dtype=object)
    # Duplicate detection uses all columns, before selecting the output subset.
    if drop_duplicates:
        f = f.drop_duplicates()
    origins = getattr(dataset, 'origins', None)
    provenance = [dict(origins[i]) if origins else {'source_file':dataset.source,'sha256':dataset.sha256,'location':dataset.location,'source_data_row':int(i)+1} for i in f.index]
    if selected_columns is not None:
        if not selected_columns:
            raise ValueError('Select at least one output column.')
        f = f[selected_columns]
    f = f.reset_index(drop=True)
    for i, item in enumerate(provenance,1):
        item['output_data_row'] = i
    operations = dict(trim=trim,drop_duplicates=drop_duplicates,drop_empty=drop_empty,numeric_columns=numeric_columns,locale=locale,selected_columns=list(f.columns),percent_rule='12,5% -> 0.125',duplicate_rule='All columns, before column selection')
    report = audit(dataset,f,operations)
    report['conversion_issues'] = issues
    report['provenance'] = provenance
    report['repeated_headers_removed'] = getattr(dataset, 'repeated_headers_removed',0)
    report['notes'] = ['PDF extraction requires comparison with source.', 'Invalid numeric values remain text and are listed in Conversion issues.', 'Percentages are decimal fractions. Numeric columns are selected explicitly.', 'Statistics use converted values and do not infer meaning of identifiers.', 'Source row is the extracted data row within the source table, not a physical PDF line.']
    return f,report

def workbook(frame, report):
    """Data plus human-readable audit, profiling and row provenance."""
    output = BytesIO()
    summary = [{'metric':f'{stage}.{k}','value':v} for stage in ['before','after'] for k,v in report[stage].items() if k!='column_profile']
    metadata = [{'property':key,'value':json.dumps(report[key],ensure_ascii=False) if isinstance(report[key],(dict,list)) else str(report[key])} for key in ['source_file','source_sha256','source_location','operations','notes','repeated_headers_removed']]
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        for name, df in [('Data',frame),('Quality',pd.DataFrame(summary)),('Columns',pd.DataFrame(report['after']['column_profile'])),('Audit',pd.DataFrame(metadata)),('Provenance',pd.DataFrame(report['provenance'])),('Conversion issues',pd.DataFrame(report['conversion_issues'],columns=['source_data_row','column','original_value','reason']))]:
            df.to_excel(writer,sheet_name=name,index=False)
        from openpyxl.styles import Font, PatternFill, Alignment
        for sheet in writer.book:
            sheet.freeze_panes = 'A2'
            sheet.auto_filter.ref = sheet.dimensions
            for cell in sheet[1]:
                cell.font = Font(bold=True,color='FFFFFF')
                cell.fill = PatternFill('solid',fgColor='17354A')
            for column in sheet.columns:
                letter = column[0].column_letter
                sheet.column_dimensions[letter].width = min(65,max(14,max(len(str(c.value or '')) for c in column)+2))
                for cell in column:
                    if isinstance(cell.value,str): cell.data_type='s'
                    cell.alignment = Alignment(vertical='top',wrap_text=True)
    return output.getvalue()

def batch(files, fmt='xlsx', load_options=None, prepare_options=None):
    """Process every table independently; failures are explicit in manifest.json."""
    if len(files)>20 or sum(len(data) for _,data in files)>100*1024*1024:
        raise ValueError('Batch limit: 20 files and 100 MB total.')
    out=BytesIO(); manifest=[]
    with ZipFile(out,'w',ZIP_DEFLATED) as z:
        for file_index,(name,data) in enumerate(files,1):
            try:
                tables=load(data,name,**(load_options or {}))
            except Exception as exc:
                manifest.append({'source':name,'status':'failed','reason':str(exc)}); continue
            for table_index,ds in enumerate(tables,1):
                try:
                    f,r=prepare(ds,**(prepare_options or {}))
                    stem = re.sub(r'[^\w.-]','_',Path(name).stem)[:70] or 'file'
                    base=f'{file_index:02d}_{stem}_table_{table_index:02d}'
                    z.writestr(base+'.'+fmt,workbook(f,r) if fmt=='xlsx' else export(f,fmt))
                    z.writestr(base+'_audit.json',json.dumps(r,ensure_ascii=False,indent=2))
                    manifest.append({'source':name,'table':ds.label,'status':'success','output':base+'.'+fmt,'rows':len(f),'conversion_issues':len(r['conversion_issues'])})
                except Exception as exc:
                    manifest.append({'source':name,'table':ds.label,'status':'failed','reason':str(exc)})
        z.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2))
    return out.getvalue(),manifest

def render_pdf_page(data, page_index):
    import pypdfium2 as pdfium
    document=pdfium.PdfDocument(data)
    try:
        page=document[page_index]
        try:
            bitmap=page.render(scale=1.25)
            try: return bitmap.to_pil().copy()
            finally: bitmap.close()
        finally: page.close()
    finally: document.close()
