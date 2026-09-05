from __future__ import annotations

import io
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from PIL import Image

from .domain import RasterPageSource, RasterTarget
from .pwg import read_pwg_raster


SUPPORTED_DOCUMENT_TYPES = {
    "application/pdf",
    "application/postscript",
    "image/jpeg",
    "image/png",
    "image/pwg-raster",
    "image/urf",
}
PDF_PAGE_SIZE = re.compile(
    r"^Page\s+(\d+)\s+size:\s+([0-9.]+)\s+x\s+([0-9.]+)\s+pts", re.MULTILINE
)
PDF_PAGE_COUNT = re.compile(r"^Pages:\s+(\d+)\s*$", re.MULTILINE)


def _run(command: list[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "LC_ALL": "C"},
        )
    except FileNotFoundError as exc:
        raise RuntimeError(f"Document converter is unavailable: {command[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Document conversion timed out: {command[0]}") from exc
    except subprocess.CalledProcessError as exc:
        message = (exc.stderr or exc.stdout or str(exc)).strip()
        raise RuntimeError(f"Document conversion failed: {message}") from exc


def _pdf_sizes(output: str) -> list[tuple[float, float]]:
    count_match = PDF_PAGE_COUNT.search(output)
    if count_match is None:
        raise RuntimeError("pdfinfo did not report a page count")
    count = int(count_match.group(1))
    maximum_pages = max(1, int(os.getenv("ZPLGRID_DOCUMENT_MAX_PAGES", "100")))
    if count > maximum_pages:
        raise RuntimeError(f"Document has {count} pages; the configured maximum is {maximum_pages}")
    by_page = {
        int(page): (float(width) * 25.4 / 72.0, float(height) * 25.4 / 72.0)
        for page, width, height in PDF_PAGE_SIZE.findall(output)
    }
    sizes = [by_page[index] for index in range(1, count + 1) if index in by_page]
    if len(sizes) != count:
        raise RuntimeError("pdfinfo did not report every PDF page size")
    return sizes


def _rasterize_pdf(path: Path, *, dpi: int, output_dir: Path) -> list[RasterPageSource]:
    initial = _run(["pdfinfo", str(path)], timeout=15).stdout
    count_match = PDF_PAGE_COUNT.search(initial)
    if count_match is None:
        raise RuntimeError("pdfinfo did not report a page count")
    page_count = int(count_match.group(1))
    details = _run(
        ["pdfinfo", "-f", "1", "-l", str(page_count), str(path)], timeout=20
    ).stdout
    sizes = _pdf_sizes(details)
    prefix = output_dir / "page"
    converter = "pdftocairo" if shutil.which("pdftocairo") else "pdftoppm"
    _run(
        [
            converter,
            "-png",
            "-r",
            str(dpi),
            "-f",
            "1",
            "-l",
            str(page_count),
            str(path),
            str(prefix),
        ],
        timeout=max(60, page_count * 10),
    )
    files = sorted(output_dir.glob("page-*.png"), key=lambda item: int(item.stem.rsplit("-", 1)[-1]))
    if len(files) != page_count:
        raise RuntimeError("PDF rasterization produced an unexpected number of pages")
    return [
        RasterPageSource(data=file.read_bytes(), mime_type="image/png", width_mm=size[0], height_mm=size[1])
        for file, size in zip(files, sizes, strict=True)
    ]


def prepare_source_document(
    data: bytes,
    *,
    mime_type: str,
    target: RasterTarget,
) -> tuple[RasterPageSource, ...]:
    mime_type = mime_type.split(";", 1)[0].strip().lower()
    if mime_type not in SUPPORTED_DOCUMENT_TYPES:
        raise ValueError(f"Unsupported document MIME type: {mime_type or 'unset'}")
    maximum_bytes = max(1, int(os.getenv("ZPLGRID_MAX_SOURCE_DOCUMENT_BYTES", str(32 * 1024 * 1024))))
    if not data or len(data) > maximum_bytes:
        raise ValueError(f"Source document must contain between 1 and {maximum_bytes} bytes")
    if mime_type in {"image/png", "image/jpeg"}:
        try:
            with Image.open(io.BytesIO(data)) as image:
                image.verify()
        except OSError as exc:
            raise ValueError("Invalid source image") from exc
        return (
            RasterPageSource(
                data=data,
                mime_type=mime_type,
                width_mm=target.width_mm,
                height_mm=target.height_mm,
            ),
        )
    suffix = {
        "application/pdf": ".pdf",
        "application/postscript": ".ps",
        "image/pwg-raster": ".pwg",
        "image/urf": ".urf",
    }[mime_type]
    with tempfile.TemporaryDirectory(prefix="printhub-document-") as temporary:
        output_dir = Path(temporary)
        source = output_dir / f"source{suffix}"
        source.write_bytes(data)
        if mime_type in {"image/pwg-raster", "image/urf"}:
            return tuple(RasterPageSource(**page) for page in read_pwg_raster(source))
        if mime_type == "application/postscript":
            converted = output_dir / "converted.pdf"
            _run(
                [
                    "gs",
                    "-q",
                    "-dSAFER",
                    "-dBATCH",
                    "-dNOPAUSE",
                    "-sDEVICE=pdfwrite",
                    f"-sOutputFile={converted}",
                    str(source),
                ],
                timeout=60,
            )
            source = converted
        return tuple(_rasterize_pdf(source, dpi=target.dpi, output_dir=output_dir))
