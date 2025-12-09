from fastapi import APIRouter, UploadFile, File, Query
from fastapi.responses import StreamingResponse
from pypdf import PdfWriter, PdfReader
from io import BytesIO
from PIL import Image
import fitz

router = APIRouter()


@router.post("/merge-pdf")
async def merge_pdf(files: list[UploadFile] = File(...)):
    pdf_writer = PdfWriter()

    for file in files:
        content = await file.read()
        pdf_reader_stream = BytesIO(content)

        try:
            pdf_writer.append(pdf_reader_stream)
        except Exception:
            return {"error": f"Failed to process {file.filename}"}

    merged_pdf = BytesIO()
    pdf_writer.write(merged_pdf)
    merged_pdf.seek(0)

    return StreamingResponse(
        merged_pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=merged.pdf"},
    )


@router.post("/split-pdf-advanced")
async def split_pdf_advanced(
    file: UploadFile = File(...),
    pages: str = "all"  # e.g: "1-3", "2,5,7", "1-3,6,10"
):
    content = await file.read()
    pdf_stream = BytesIO(content)

    try:
        reader = PdfReader(pdf_stream)
    except Exception:
        return {"error": "Invalid PDF file"}

    # Determine pages to extract
    page_indices = []

    if pages == "all":
        page_indices = list(range(len(reader.pages)))
    else:
        ranges = pages.replace(" ", "").split(",")
        for r in ranges:
            if "-" in r:
                start, end = map(int, r.split("-"))
                page_indices.extend(list(range(start - 1, end)))
            else:
                page_indices.append(int(r) - 1)

    # Validate
    max_pages = len(reader.pages)
    for idx in page_indices:
        if idx < 0 or idx >= max_pages:
            return {"error": f"Page {idx+1} out of range"}

    # Create output PDF
    writer = PdfWriter()

    for idx in page_indices:
        writer.add_page(reader.pages[idx])

    output_pdf = BytesIO()
    writer.write(output_pdf)
    output_pdf.seek(0)

    return StreamingResponse(
        output_pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": "attachment; filename=extracted_pages.pdf"
        }
    )



@router.post("/image-to-pdf")
async def image_to_pdf(files: list[UploadFile] = File(...)):
    if not files:
        return {"error": "Please upload at least one image."}

    image_list = []

    # Sort by filename to maintain order
    files_sorted = files  # KEEP USER ORDER EXACTLY

    for file in files_sorted:
        content = await file.read()

        try:
            img = Image.open(BytesIO(content))

            # Convert images to RGB for PDF
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")

            image_list.append(img)

        except Exception:
            return {"error": f"Invalid image file: {file.filename}"}

    # Create PDF in memory
    pdf_buffer = BytesIO()

    # Save first image, append rest
    first_image = image_list[0]
    rest_images = image_list[1:]

    first_image.save(
        pdf_buffer,
        format="PDF",
        save_all=True,
        append_images=rest_images,
    )

    pdf_buffer.seek(0)

    return StreamingResponse(
        pdf_buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=images_to_pdf.pdf"},
    )


PAGE_SIZES = {
    "A4": (595, 842),
    "LETTER": (612, 792),
}


@router.post("/image-to-pdf-advanced")
async def image_to_pdf_advanced(
    files: list[UploadFile] = File(...),
    page_size: str = Query("A4", regex="^(A4|LETTER|FIT)$"),
    orientation: str = Query("portrait", regex="^(portrait|landscape)$"),
    margin: int = Query(10, ge=0, le=100),
    background: str = Query("#FFFFFF"),
    fit_mode: str = Query("contain", regex="^(contain|cover)$"),
    dpi: int = Query(72, ge=72, le=300),
):
    if not files:
        return {"error": "Please upload at least one image."}

    images = []
    files_sorted = files

    for file in files_sorted:
        content = await file.read()
        img = Image.open(BytesIO(content))

        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")

        # --- DETERMINE PAGE SIZE ---
        if page_size == "FIT":
            page_w, page_h = img.width, img.height
        else:
            page_w, page_h = PAGE_SIZES[page_size]

        if orientation == "landscape":
            page_w, page_h = page_h, page_w

        # --- COMPUTE DRAW AREA (minus margin) ---
        draw_w = page_w - (margin * 2)
        draw_h = page_h - (margin * 2)

        img_ratio = img.width / img.height
        page_ratio = draw_w / draw_h

        # --- FIT IMAGE ---
        if fit_mode == "contain":
            if img_ratio > page_ratio:
                new_w = draw_w
                new_h = int(draw_w / img_ratio)
            else:
                new_h = draw_h
                new_w = int(draw_h * img_ratio)
        else:  # "cover"
            if img_ratio < page_ratio:
                new_w = draw_w
                new_h = int(draw_w / img_ratio)
            else:
                new_h = draw_h
                new_w = int(draw_h * img_ratio)

        img_resized = img.resize((new_w, new_h), Image.LANCZOS)

        # --- CREATE PAGE CANVAS ---
        canvas = Image.new("RGB", (page_w, page_h), background)

        offset_x = (page_w - new_w) // 2
        offset_y = (page_h - new_h) // 2

        canvas.paste(img_resized, (offset_x, offset_y))
        images.append(canvas)

    # --- EXPORT PDF ---
    pdf_buffer = BytesIO()
    first_img, *rest = images

    first_img.save(
        pdf_buffer,
        format="PDF",
        save_all=True,
        append_images=rest,
        resolution=dpi,
    )

    pdf_buffer.seek(0)

    return StreamingResponse(
        pdf_buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=advanced_images_to_pdf.pdf"},
    )


@router.post("/compress-pdf-advanced")
async def compress_pdf_advanced(
    file: UploadFile = File(...),
    quality: int = Query(60, ge=10, le=95, description="JPEG quality for images"),
    image_dpi: int = Query(120, ge=72, le=300, description="Render DPI (higher = better quality, bigger file)"),
    grayscale: bool = Query(False, description="Convert pages to grayscale"),
    remove_metadata: bool = Query(True, description="Strip PDF metadata to reduce size"),
    max_pages: int | None = Query(None, ge=1, description="Compress only the first N pages (optional)"),
):
    """
    Strong PDF compression by rasterizing pages to images with configurable
    JPEG quality, DPI, grayscale and metadata options.
    """
    content = await file.read()

    # Open source PDF
    try:
        src_doc = fitz.open(stream=content, filetype="pdf")
    except Exception:
        return {"error": "Invalid PDF file"}

    page_count = src_doc.page_count

    # Determine which pages to process
    if max_pages is not None:
        page_indices = list(range(min(max_pages, page_count)))
    else:
        page_indices = list(range(page_count))

    # Zoom factor based on DPI (default PDF is 72 dpi)
    zoom = image_dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)

    new_doc = fitz.open()

    try:
        for page_index in page_indices:
            page = src_doc.load_page(page_index)
            pix = page.get_pixmap(matrix=matrix, alpha=False)

            # Convert pixmap to PIL Image
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

            if grayscale:
                img = img.convert("L")

            img_buffer = BytesIO()
            img.save(
                img_buffer,
                format="JPEG",
                quality=quality,
                optimize=True,
            )
            img_bytes = img_buffer.getvalue()

            rect = fitz.Rect(0, 0, pix.width, pix.height)
            new_page = new_doc.new_page(width=rect.width, height=rect.height)
            new_page.insert_image(rect, stream=img_bytes)

        # Optionally preserve metadata
        if not remove_metadata:
            new_doc.set_metadata(src_doc.metadata or {})

        out_buffer = BytesIO()
        new_doc.save(out_buffer, deflate=True)
        out_buffer.seek(0)

    finally:
        new_doc.close()
        src_doc.close()

    return StreamingResponse(
        out_buffer,
        media_type="application/pdf",
        headers={
            "Content-Disposition": "attachment; filename=compressed_advanced.pdf"
        },
    )
