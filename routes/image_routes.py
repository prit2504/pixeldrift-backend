from fastapi import APIRouter, UploadFile, File, Query, HTTPException, Form
from fastapi.responses import StreamingResponse
from PIL import Image, ImageEnhance, UnidentifiedImageError
import io
from io import BytesIO
import zipfile
import re
import typing


router = APIRouter()


@router.post("/compress-image-advanced")
async def compress_image_advanced(
    file: UploadFile = File(...),

    # Quality control
    quality: int = Query(75, ge=1, le=100),

    # Resize control (percentage)
    resize_percent: int = Query(100, ge=10, le=100),

    # Max dimension control
    max_width: int | None = Query(None, ge=100),
    max_height: int | None = Query(None, ge=100),

    # Output format
    format: str = Query("jpeg", regex="^(jpeg|jpg|png|webp)$"),

    # Metadata control
    keep_metadata: bool = Query(False),
):
    """
    Full-featured image compressor:
    - Quality (1–100)
    - Resize percentage
    - Max width/height resizing
    - Format conversion
    - Remove EXIF metadata
    """

    # Read file
    original_bytes = await file.read()
    image = Image.open(io.BytesIO(original_bytes))

    # Auto-convert transparency if needed
    if image.mode in ("RGBA", "P"):
        image = image.convert("RGB")

    # ----- STEP 1: Resize by percentage -----
    if resize_percent < 100:
        new_w = int(image.width * resize_percent / 100)
        new_h = int(image.height * resize_percent / 100)
        image = image.resize((new_w, new_h), Image.LANCZOS)

    # ----- STEP 2: Check max width/height -----
    if max_width or max_height:
        ratio = image.width / image.height

        if max_width and image.width > max_width:
            new_w = max_width
            new_h = int(max_width / ratio)
            image = image.resize((new_w, new_h), Image.LANCZOS)

        if max_height and image.height > max_height:
            new_h = max_height
            new_w = int(max_height * ratio)
            image = image.resize((new_w, new_h), Image.LANCZOS)

    # ----- STEP 3: Save with compression -----
    buffer = io.BytesIO()

    save_params = {
        "format": format.upper(),
        "optimize": True,
    }

    # JPEG/WebP compression control
    if format.lower() in ["jpeg", "jpg", "webp"]:
        save_params["quality"] = quality

    # Remove metadata unless required
    if not keep_metadata:
        image.info.pop("exif", None)

    image.save(buffer, **save_params)
    buffer.seek(0)

    # Determine filename
    ext = format.lower()
    filename = f"compressed.{ext}"

    return StreamingResponse(
        buffer,
        media_type=f"image/{ext}",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


#########  Converter


SUPPORTED_OUTPUTS = {
    "jpeg": "JPEG",
    "jpg": "JPEG",
    "png": "PNG",
    "webp": "WEBP",
    "bmp": "BMP",
    "tiff": "TIFF",
}


def sanitize_filename(name: str) -> str:
    """Remove unsafe characters from filenames."""
    return re.sub(r"[^a-zA-Z0-9_\-\.]", "_", name)


@router.post("/convert-image")
async def convert_image(
    files: list[UploadFile] = File(...),
    out_format: str = Form(...),              # "jpg" | "png" | "webp" | etc.
    rename_to: str = Form(None),              # Optional rename ("my-photo")
):
    if out_format.lower() not in SUPPORTED_OUTPUTS:
        return {"error": "Unsupported output format."}

    output_ext = out_format.lower()
    pil_format = SUPPORTED_OUTPUTS[output_ext]

    # Single file conversion
    if len(files) == 1:
        file = files[0]
        content = await file.read()
        img = Image.open(BytesIO(content))

        # Convert transparent images properly
        if img.mode in ("RGBA", "P") and pil_format == "JPEG":
            img = img.convert("RGB")

        buffer = BytesIO()
        img.save(buffer, pil_format)
        buffer.seek(0)

        # Handle renaming
        if rename_to:
            filename = f"{sanitize_filename(rename_to)}.{output_ext}"
        else:
            base = file.filename.rsplit(".", 1)[0]
            filename = f"{sanitize_filename(base)}_converted.{output_ext}"

        return StreamingResponse(
            buffer,
            media_type=f"image/{output_ext}",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )

    # Multi-file: return ZIP
    zip_buffer = BytesIO()

    with zipfile.ZipFile(zip_buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for index, file in enumerate(files, start=1):
            content = await file.read()
            img = Image.open(BytesIO(content))

            # Convert mode correctly
            if img.mode in ("RGBA", "P") and pil_format == "JPEG":
                img = img.convert("RGB")

            buffer = BytesIO()
            img.save(buffer, pil_format)
            buffer.seek(0)

            # Naming logic
            if rename_to:
                filename = f"{sanitize_filename(rename_to)}_{index}.{output_ext}"
            else:
                base = file.filename.rsplit(".", 1)[0]
                filename = f"{sanitize_filename(base)}_converted.{output_ext}"

            zf.writestr(filename, buffer.getvalue())

    zip_buffer.seek(0)

    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=converted_images.zip"}
    )



########## Resize image

FORMAT_MAP = {
    "jpeg": ("JPEG", "image/jpeg", "jpg"),
    "png": ("PNG", "image/png", "png"),
    "webp": ("WEBP", "image/webp", "webp"),
}


def open_image_safely(data: bytes) -> Image.Image:
    img = Image.open(BytesIO(data))
    # Convert palette/rgba to RGB for safe saving as JPEG
    if img.mode in ("P", "LA", "RGBA"):
        img = img.convert("RGBA") if img.mode == "RGBA" else img.convert("RGB")
    return img


@router.post("/resize-image")
async def resize_image_new(
    files: typing.List[UploadFile] = File(...),

    width: int | None = Form(None),
    height: int | None = Form(None),
    percentage: int | None = Form(None),

    keep_ratio: bool = Form(True),
    prevent_upscale: bool = Form(True),

    out_format: str = Form("jpeg"),
    quality: int = Form(85),
    sharpen: float = Form(1.0),
):
    """
    Fixed version:
    - Correct handling for None/empty values
    - Accepts Form() not Query()
    """

    if not files:
        raise HTTPException(400, "No files uploaded.")

    key = out_format.lower()
    if key not in FORMAT_MAP:
        raise HTTPException(400, "Unsupported output format")

    pillow_fmt, mime_type, ext = FORMAT_MAP[key]

    results = []

    for upload in files:
        content = await upload.read()

        try:
            img = open_image_safely(content)
        except UnidentifiedImageError:
            raise HTTPException(400, f"Unsupported or corrupted image: {upload.filename}")

        orig_w, orig_h = img.size

        # -------------------------------
        # FIXED: SIZE COMPUTATION LOGIC
        # -------------------------------
        if percentage is not None:
            new_w = max(1, int(orig_w * percentage / 100))
            new_h = max(1, int(orig_h * percentage / 100))

        elif width is not None and height is None:
            if keep_ratio:
                r = width / orig_w
                new_w = width
                new_h = int(orig_h * r)
            else:
                new_w = width
                new_h = orig_h

        elif height is not None and width is None:
            if keep_ratio:
                r = height / orig_h
                new_h = height
                new_w = int(orig_w * r)
            else:
                new_h = height
                new_w = orig_w

        elif width is not None and height is not None:
            if keep_ratio:
                r = min(width / orig_w, height / orig_h)
                new_w = int(orig_w * r)
                new_h = int(orig_h * r)
            else:
                new_w = width
                new_h = height

        else:
            raise HTTPException(400, "Provide width, height, or percentage.")

        # Prevent upscaling
        if prevent_upscale:
            new_w = min(new_w, orig_w)
            new_h = min(new_h, orig_h)

        # Resize
        img_resized = img.resize((new_w, new_h), Image.LANCZOS)

        # Sharpen
        if sharpen != 1.0 and sharpen > 0:
            enhancer = ImageEnhance.Sharpness(img_resized)
            img_resized = enhancer.enhance(sharpen)

        # Convert for JPEG
        if pillow_fmt == "JPEG" and img_resized.mode in ("RGBA", "LA"):
            img_resized = img_resized.convert("RGB")

        # Output buffer
        buf = BytesIO()
        save_kwargs = {}
        if pillow_fmt in ("JPEG", "WEBP"):
            save_kwargs["quality"] = quality
            if pillow_fmt == "JPEG":
                save_kwargs["optimize"] = True

        img_resized.save(buf, format=pillow_fmt, **save_kwargs)
        buf.seek(0)

        base = upload.filename.rsplit(".", 1)[0]
        results.append((f"{base}-resized.{ext}", buf))

    # 1 file → direct download
    if len(results) == 1:
        fn, buf = results[0]
        return StreamingResponse(
            buf,
            media_type=mime_type,
            headers={"Content-Disposition": f'attachment; filename="{fn}"'}
        )

    # Multiple → ZIP
    zip_buf = BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as z:
        for fn, buf in results:
            z.writestr(fn, buf.getvalue())
    zip_buf.seek(0)

    return StreamingResponse(
        zip_buf,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="resized-images.zip"'}
    )
