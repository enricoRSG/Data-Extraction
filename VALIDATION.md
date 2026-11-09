# Validation - 5 November 2026
26 automated tests passed on Python 3.12.

Coverage: interface loading, cleaning interaction, numeric-conversion interaction,
batch screen; digital PDF extraction against reference output; CSV/XLSX/JSON
round trips; multiple workbook sheets; text identifiers; encoding/separators;
literal formula-like XLSX strings; cleaning immutability; descriptive statistics;
malformed inputs; PDF header collisions; PDFs without ruled tables; Italian and
English numeric parsing; currency and percentage handling; invalid numeric text
retention; multipage merging; schema rejection; repeated headers; row provenance
after cleaning; six-sheet Excel report; batch failures, filename collisions and
limits; PDF page preview rendering.

Install requirements-dev.txt to run all tests, including synthetic PDF fixtures.
Run from this directory: python -m unittest discover -s tests -v

Demonstration checks:
- Sales: 7 extracted records -> 6 after duplicate removal; EUR 2,850 total.
- Contacts: 4 extracted records -> 3 after duplicate removal; one missing email.
- Products: EUR 1,576.40 total; 12.5% -> fraction 0.125.
- Multipage sales: 4 merged records; EUR 2,750.50 total; page provenance retained.

PDF pages and the cover were rendered and visually inspected. All data is synthetic.
Output workbooks were reopened to check sheet structure, values and cell types.
No validation on customer documents or on a physical Windows PC was performed.
There is no universal extraction-accuracy guarantee; scope is digital bordered tables.
OCR remains a future extension.
