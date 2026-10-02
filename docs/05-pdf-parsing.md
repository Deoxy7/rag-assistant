# 05 — PDF parsing

**Status:** not yet written — filled in Phase 2.

What this doc will cover: How a PDF stores text, how PyMuPDF extracts it as structured blocks with page_number, char_start and char_end, pdfplumber for tables, and how headers, footers and multi-column pages are handled.

## Planned sections

1. In one paragraph
2. Why it exists
3. Where it sits
4. The flow
5. The code
6. Data in / data out
7. Decisions & alternatives — Decision Cards #4, #5
7a. Prerequisite concepts — PDF objects and content streams, fonts and glyphs, text blocks/lines/spans, bounding boxes, reading order, multi-column layout, Unicode normalisation, character offsets
7b. What if we used something else?
8. Failure modes
9. Try it yourself
10. Numbers — parse time per page, blocks per page, pages with tables
11. Interview talking points
12. Check yourself
13. New terms added to the glossary

Planned diagrams: parsing pipeline, page → block decomposition
