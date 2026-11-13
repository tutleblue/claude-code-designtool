"""시험용 작업물 만들기: 글·코드·표·그림·PDF·Word·PowerPoint·Excel·소리. 바깥 라이브러리 없이 만든다."""
from __future__ import annotations

import struct
import zipfile
import zlib
from pathlib import Path

CT = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'


def png(w: int, h: int, color=(200, 60, 40)) -> bytes:
    raw = b"".join(b"\0" + bytes(color) * w for _ in range(h))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + \
        chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def pdf(text: str = "Hello PDF") -> bytes:
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        None,
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    stream = f"BT /F1 24 Tf 40 100 Td ({text}) Tj ET".encode()
    objs[3] = b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"
    out = bytearray(b"%PDF-1.4\n")
    offs = []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for o in offs:
        out += f"{o:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def docx(path: Path) -> None:
    W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    body = (f'{CT}<w:document {W}><w:body>'
            '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>보고서 제목</w:t></w:r></w:p>'
            '<w:p><w:r><w:t>첫 문단입니다. </w:t></w:r><w:r><w:t>이어지는 글.</w:t></w:r></w:p>'
            '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>칸1</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>칸2</w:t></w:r></w:p></w:tc></w:tr></w:tbl>'
            '<w:p><w:r><w:t>마지막 문단</w:t></w:r></w:p></w:body></w:document>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", f'{CT}<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        z.writestr("_rels/.rels", f'{CT}<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="r1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        z.writestr("word/document.xml", body)


def pptx(path: Path) -> None:
    P = ('xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
         'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"')
    def sp(text: str, title: bool = False) -> str:
        ph = '<p:nvSpPr><p:cNvPr id="1" name="t"/><p:cNvSpPr/><p:nvPr><p:ph type="title"/></p:nvPr></p:nvSpPr>' if title else \
            '<p:nvSpPr><p:cNvPr id="2" name="b"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>'
        return f'<p:sp>{ph}<p:txBody><a:p><a:r><a:t>{text}</a:t></a:r></a:p></p:txBody></p:sp>'
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", f'{CT}<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        for n, (t, b) in enumerate([("첫 장 제목", "본문 하나"), ("둘째 장", "요점 둘")], 1):
            z.writestr(f"ppt/slides/slide{n}.xml", f'{CT}<p:sld {P}><p:cSld><p:spTree>{sp(t, True)}{sp(b)}</p:spTree></p:cSld></p:sld>')


def xlsx(path: Path) -> None:
    S = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", f'{CT}<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        z.writestr("xl/workbook.xml", f'{CT}<workbook {S}><sheets><sheet name="성적" sheetId="1"/></sheets></workbook>')
        z.writestr("xl/sharedStrings.xml", f'{CT}<sst {S}><si><t>이름</t></si><si><t>점수</t></si><si><t>콩쥐</t></si></sst>')
        z.writestr("xl/worksheets/sheet1.xml", f'{CT}<worksheet {S}><sheetData>'
                   '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>'
                   '<row r="2"><c r="A2" t="s"><v>2</v></c><c r="B2"><v>95</v></c></row></sheetData></worksheet>')


def make_all(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "notes.md").write_text("# 회의 메모\n\n첫 문단은 여기.\n둘째 줄도 같은 문단.\n\n- 할 일 하나\n- 할 일 둘\n\n| 이름 | 점수 |\n|---|---|\n| 콩쥐 | 95 |\n", encoding="utf-8")
    (root / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    (root / "scores.csv").write_text("이름,점수\n콩쥐,95\n팥쥐,80\n", encoding="utf-8")
    (root / "picture.png").write_bytes(png(120, 80))
    (root / "paper.pdf").write_bytes(pdf())
    docx(root / "report.docx")
    pptx(root / "slides.pptx")
    xlsx(root / "table.xlsx")
