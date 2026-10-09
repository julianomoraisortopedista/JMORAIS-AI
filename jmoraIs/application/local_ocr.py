"""Local OCR for photographed or scanned exam reports (Tesseract, Portuguese).

Runs entirely on this machine: the image never leaves it and never reaches an AI model.
The recognised text follows the same path as any other document (identifier pre-fill,
de-identification, physician preview) before anything is sent to the LLM gateway.
OCR can misread characters, including identifiers: the physician reviews the
de-identified preview before extraction.
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile


class OCRUnavailable(RuntimeError):
    """Local OCR tools are not installed or failed; caller explains the fallback."""


IMAGE_SIGNATURES = ((b"\xff\xd8\xff", ".jpg"), (b"\x89PNG\r\n\x1a\n", ".png"))
MAX_OCR_PAGES = 10
PAGE_TIMEOUT_SECONDS = 60
MIN_TEXT_CHARS = 40


def image_suffix(content: bytes) -> str | None:
    """File type from the content itself, never from the file name."""
    return next((suffix for signature, suffix in IMAGE_SIGNATURES if content.startswith(signature)), None)


def available() -> bool:
    return shutil.which("tesseract") is not None


def _run(command: list[str], timeout: int) -> str:
    try:
        result = subprocess.run(command, capture_output=True, timeout=timeout, check=False,
                                env={"PATH": os.environ.get("PATH", ""), "OMP_THREAD_LIMIT": "1"})
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise OCRUnavailable("leitura local da imagem falhou") from exc
    if result.returncode != 0:
        raise OCRUnavailable("leitura local da imagem falhou")
    return result.stdout.decode("utf-8", errors="replace")


def _tesseract(image: Path) -> str:
    return _run(["tesseract", str(image), "stdout", "-l", "por", "--psm", "3"], PAGE_TIMEOUT_SECONDS)


def ocr_image(content: bytes) -> str:
    suffix = image_suffix(content)
    if suffix is None:
        raise OCRUnavailable("formato de imagem não suportado (use JPG ou PNG)")
    if not available():
        raise OCRUnavailable("leitor de imagens não instalado")
    with tempfile.TemporaryDirectory(prefix="jm-ocr-") as work:  # private (0700), removed on exit
        image = Path(work) / ("page" + suffix)
        image.write_bytes(content)
        return _tesseract(image)


def ocr_pdf(content: bytes, max_pages: int = MAX_OCR_PAGES) -> str:
    """Render scanned PDF pages at 300 dpi and recognise each page locally."""
    if not available() or shutil.which("pdftoppm") is None:
        raise OCRUnavailable("leitor de PDF escaneado não instalado")
    with tempfile.TemporaryDirectory(prefix="jm-ocr-") as work:
        source = Path(work) / "scan.pdf"
        source.write_bytes(content)
        _run(["pdftoppm", "-r", "300", "-gray", "-f", "1", "-l", str(max_pages), "-png", str(source),
              str(Path(work) / "page")], PAGE_TIMEOUT_SECONDS * 2)
        pages = sorted(Path(work).glob("page*.png"))
        if not pages:
            raise OCRUnavailable("PDF sem páginas legíveis")
        return "\n".join(_tesseract(page) for page in pages[:max_pages])
