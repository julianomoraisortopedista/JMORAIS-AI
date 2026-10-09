import shutil
import subprocess

import pytest

from jmoraIs.application import case_intake, local_ocr
from jmoraIs.application.case_intake import CaseIntakeRejected, extract_text, prepare_documents
from jmoraIs.application.deidentification import PatientIdentifiers

JPEG = b"\xff\xd8\xff\xe0" + b"0" * 64
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64
DRAW = b"q 595 0 0 842 0 0 cm /Im0 Do Q"
REPORT = "Ressonancia magnetica do joelho direito. Condropatia grau IV no compartimento medial."


def blank_pdf() -> bytes:
    return pdf([b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
                b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] >>"])


def pdf(objects: list[bytes]) -> bytes:
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return bytes(out)


def test_image_type_comes_from_content_not_name():
    assert local_ocr.image_suffix(JPEG) == ".jpg" and local_ocr.image_suffix(PNG) == ".png"
    assert local_ocr.image_suffix(b"%PDF-1.4") is None
    with pytest.raises(local_ocr.OCRUnavailable):
        local_ocr.ocr_image(b"GIF89a" + b"0" * 64)


def test_photo_is_read_locally_and_then_deidentified(monkeypatch):
    monkeypatch.setattr(local_ocr, "ocr_image", lambda content: "Paciente: JOSE CARLOS DA SILVA\n" + REPORT)
    _, docs = prepare_documents([("laudo.JPG", JPEG)], "", PatientIdentifiers(name="José Carlos da Silva"))
    assert "SILVA" not in docs[0].text and "Condropatia grau IV" in docs[0].text


def test_scanned_pdf_falls_back_to_local_ocr(monkeypatch):
    calls = []
    monkeypatch.setattr(local_ocr, "ocr_pdf", lambda content: calls.append(content) or REPORT)
    assert extract_text("scan.pdf", blank_pdf()) == REPORT and len(calls) == 1


def test_ocr_unavailable_or_illegible_is_refused_with_guidance(monkeypatch):
    def missing(content):
        raise local_ocr.OCRUnavailable("leitor de imagens não instalado")
    monkeypatch.setattr(local_ocr, "ocr_image", missing)
    with pytest.raises(CaseIntakeRejected, match="Digite o laudo"):
        extract_text("foto.png", PNG)
    monkeypatch.setattr(local_ocr, "ocr_image", lambda content: "  ~ ")
    with pytest.raises(CaseIntakeRejected, match="sem texto legível"):
        extract_text("foto.png", PNG)
    with pytest.raises(CaseIntakeRejected, match="foto"):
        extract_text("planilha.xlsx", b"PK")


def test_ocr_tool_failure_and_timeout_are_contained(monkeypatch, tmp_path):
    monkeypatch.setattr(local_ocr, "available", lambda: True)
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("tesseract", 60)
    monkeypatch.setattr(subprocess, "run", timeout)
    with pytest.raises(local_ocr.OCRUnavailable):
        local_ocr.ocr_image(PNG)
    assert case_intake.local_ocr is local_ocr


@pytest.mark.skipif(not (shutil.which("tesseract") and shutil.which("pdftoppm")), reason="local OCR tools not installed")
def test_real_local_ocr_reads_photo_and_scanned_pdf(tmp_path):
    lines = ["Paciente: JOSE CARLOS DA SILVA", "Ressonancia magnetica do joelho direito", "Condropatia grau IV no compartimento medial"]
    stream = b"BT /F1 16 Tf 60 760 Td 22 TL " + b"".join(b"(" + line.encode() + b") ' " for line in lines) + b"ET"
    text_pdf = pdf([b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
                    b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
                    b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
                    b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream"])
    (tmp_path / "text.pdf").write_bytes(text_pdf)
    subprocess.run(["pdftoppm", "-jpeg", "-singlefile", "-scale-to-x", "1240", "-scale-to-y", "1754",
                    str(tmp_path / "text.pdf"), str(tmp_path / "photo")], check=True, timeout=60)
    photo = (tmp_path / "photo.jpg").read_bytes()
    assert "Condropatia" in extract_text("foto.jpeg", photo)
    scanned = pdf([b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
                   b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /XObject << /Im0 4 0 R >> >> /Contents 5 0 R >>",
                   b"<< /Type /XObject /Subtype /Image /Width 1240 /Height 1754 /ColorSpace /DeviceRGB /BitsPerComponent 8"
                   b" /Filter /DCTDecode /Length %d >>\nstream\n" % len(photo) + photo + b"\nendstream",
                   b"<< /Length %d >>\nstream\n" % len(DRAW) + DRAW + b"\nendstream"])
    _, docs = prepare_documents([("scan.pdf", scanned)], "", PatientIdentifiers(name="José Carlos da Silva"))
    assert "Condropatia" in docs[0].text and "SILVA" not in docs[0].text.upper()
