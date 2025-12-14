from fastapi import APIRouter, UploadFile, File, Query, HTTPException, Form
from fastapi.responses import StreamingResponse
from PIL import Image, ImageEnhance, UnidentifiedImageError, ImageOps
import io
from io import BytesIO
import zipfile
import re
import typing


router = APIRouter()


# ------------------ CONFIG ------------------

MAX_IMAGE_SIZE = 15 * 1024 * 1024  # 15MB
SUPPORTED_FORMATS = {"jpeg", "jpg", "png", "webp"}

# ------------------ HELPERS ------------------

def sanitize_filename(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]", "_", name)


def calculate_new_size(
    image: Image.Image,
    resize_percent: int,
    max_width: int | None,
    max_height: int | None,
):
    w, h = image.size
    scale = resize_percent / 100

    new_w = int(w * scale)
    new_h = int(h * scale)

    if max_width and new_w > max_width:
        ratio = max_width / new_w
        new_w = max_width
        new_h = int(new_h * ratio)

    if max_height and new_h > max_height:
        ratio = max_height / new_h
        new_h = max_height
        new_w = int(new_w * ratio)

    return new_w, new_h


# ------------------ ROUTE ------------------

@router.post("/compress-image-advanced")
async def compress_image_advanced(
    file: UploadFile = File(...),

    quality: int = Query(75, ge=1, le=100),
    resize_percent: int = Query(100, ge=10, le=100),
    max_width: int | None = Query(None, ge=100),
    max_height: int | None = Query(None, ge=100),
    format: str = Query("jpeg"),
    keep_metadata: bool = Query(False),
):
    """
    Advanced Image Compression API
    - Quality control
    - Resize percentage
    - Max width / height
    - Format conversion
    - Metadata removal
    """

    format = format.lower()
    if format not in SUPPORTED_FORMATS:
        raise HTTPException(400, "Unsupported output format")

    # -------- READ & VALIDATE FILE --------
    original_bytes = await file.read()

    if not original_bytes:
        raise HTTPException(400, "Empty file")

    if len(original_bytes) > MAX_IMAGE_SIZE:
        raise HTTPException(413, "Image too large (max 15MB)")

    try:
        image = Image.open(io.BytesIO(original_bytes))
    except Exception:
        raise HTTPException(400, "Invalid image file")

    # -------- FIX ORIENTATION --------
    image = ImageOps.exif_transpose(image)

    # -------- MODE CONVERSION --------
    if image.mode in ("RGBA", "P"):
        image = image.convert("RGB")

    # -------- RESIZE (SINGLE PASS) --------
    new_size = calculate_new_size(
        image, resize_percent, max_width, max_height
    )

    if new_size != image.size:
        image = image.resize(new_size, Image.LANCZOS)

    # -------- METADATA --------
    if not keep_metadata:
        image.info.clear()

    # -------- SAVE OPTIMIZED --------
    buffer = io.BytesIO()

    save_params: dict = {"optimize": True}

    if format in ("jpeg", "jpg", "webp"):
        save_params["quality"] = quality
        save_params["subsampling"] = 2

    if format == "png":
        save_params["compress_level"] = 9

    pil_format = "JPEG" if format in ("jpeg", "jpg") else format.upper()

    image.save(buffer, format=pil_format, **save_params)
    buffer.seek(0)

    output_bytes = buffer.getvalue()
    buffer.seek(0)

    filename = sanitize_filename(f"compressed.{format}")

    # -------- STREAM WITH CONTENT-LENGTH (PROGRESS BAR WORKS) --------
    return StreamingResponse(
        buffer,
        media_type=f"image/{format}",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(output_bytes)),
            "Cache-Control": "no-store",
        },
    )

######################## COnvert Image

# ---------------- CONFIG ----------------

MAX_IMAGE_SIZE = 15 * 1024 * 1024  # 15MB

SUPPORTED_OUTPUTS = {
    "jpeg": "JPEG",
    "jpg": "JPEG",
    "png": "PNG",
    "webp": "WEBP",
    "bmp": "BMP",
    "tiff": "TIFF",
}

# ---------------- HELPERS ----------------

def sanitize_filename(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]", "_", name)


def load_image(file: UploadFile) -> Image.Image:
    data = file.file.read()
    if len(data) > MAX_IMAGE_SIZE:
        raise HTTPException(413, "Image too large")

    try:
        img = Image.open(BytesIO(data))
        img = ImageOps.exif_transpose(img)
        return img
    except Exception:
        raise HTTPException(400, f"Invalid image: {file.filename}")


def prepare_image(img: Image.Image, out_format: str) -> Image.Image:
    if img.mode in ("RGBA", "P") and out_format in ("jpeg", "jpg", "bmp"):
        return img.convert("RGB")
    return img


# ---------------- ROUTE ----------------

@router.post("/convert-image")
async def convert_image(
    files: list[UploadFile] = File(...),
    out_format: str = Form(...),
    rename_to: str | None = Form(None),
):
    out_format = out_format.lower()

    if out_format not in SUPPORTED_OUTPUTS:
        raise HTTPException(400, "Unsupported output format")

    pil_format = SUPPORTED_OUTPUTS[out_format]

    # -------- SINGLE FILE --------
    if len(files) == 1:
        file = files[0]
        img = prepare_image(load_image(file), out_format)

        buffer = BytesIO()
        img.save(buffer, pil_format, optimize=True)
        buffer.seek(0)

        base = rename_to or file.filename.rsplit(".", 1)[0]
        filename = f"{sanitize_filename(base)}.{out_format}"

        return StreamingResponse(
            buffer,
            media_type=f"image/{out_format}",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Content-Length": str(len(buffer.getvalue())),
                "Cache-Control": "no-store",
            },
        )

    # -------- MULTI FILE → ZIP --------
    zip_buffer = BytesIO()

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zipf:
        for idx, file in enumerate(files, start=1):
            img = prepare_image(load_image(file), out_format)

            img_buffer = BytesIO()
            img.save(img_buffer, pil_format, optimize=True)

            base = rename_to or file.filename.rsplit(".", 1)[0]
            name = f"{sanitize_filename(base)}_{idx}.{out_format}"

            zipf.writestr(name, img_buffer.getvalue())

    zip_buffer.seek(0)

    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="converted_images.zip"',
            "Content-Length": str(len(zip_buffer.getvalue())),
            "Cache-Control": "no-store",
        },
    )


#####################3 Resize image







# ---------------- CONFIG ----------------

MAX_IMAGE_SIZE = 15 * 1024 * 1024  # 15MB

FORMAT_MAP = {
    "jpeg": ("JPEG", "image/jpeg", "jpg"),
    "png": ("PNG", "image/png", "png"),
    "webp": ("WEBP", "image/webp", "webp"),
}

# ---------------- HELPERS ----------------

def sanitize_filename(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]", "_", name)


def open_image(data: bytes) -> Image.Image:
    if len(data) > MAX_IMAGE_SIZE:
        raise HTTPException(413, "Image too large")

    try:
        img = Image.open(BytesIO(data))
        return ImageOps.exif_transpose(img)
    except UnidentifiedImageError:
        raise HTTPException(400, "Invalid image")


def compute_size(
    ow: int,
    oh: int,
    tw: int,
    th: int,
    mode: str,
):
    if mode == "stretch":
        return tw, th

    r = ow / oh
    if tw / th > r:
        nh = th
        nw = int(th * r)
    else:
        nw = tw
        nh = int(tw / r)

    return nw, nh


# ---------------- ROUTE ----------------

@router.post("/resize-image")
async def resize_image(
    files: typing.List[UploadFile] = File(...),

    width: int = Form(...),
    height: int = Form(...),

    resize_mode: str = Form("fit"),   # fit | stretch | pad
    bg_color: str = Form("#ffffff"),

    out_format: str = Form("jpeg"),
    quality: int = Form(85),
    sharpen: float = Form(1.0),
):
    if not files:
        raise HTTPException(400, "No files uploaded")

    if resize_mode not in {"fit", "stretch", "pad"}:
        raise HTTPException(400, "Invalid resize mode")

    fmt_key = out_format.lower()
    if fmt_key not in FORMAT_MAP:
        raise HTTPException(400, "Unsupported output format")

    pillow_fmt, mime, ext = FORMAT_MAP[fmt_key]
    results: list[tuple[str, BytesIO]] = []

    for upload in files:
        data = await upload.read()
        img = open_image(data)

        ow, oh = img.size
        rw, rh = compute_size(ow, oh, width, height, resize_mode)

        resized = img.resize((rw, rh), Image.LANCZOS)

        if sharpen > 1:
            resized = ImageEnhance.Sharpness(resized).enhance(sharpen)

        # PAD MODE
        if resize_mode == "pad":
            if bg_color == "transparent" and pillow_fmt != "JPEG":
                canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            else:
                canvas = Image.new("RGB", (width, height), bg_color)

            x = (width - rw) // 2
            y = (height - rh) // 2
            canvas.paste(resized, (x, y))
            resized = canvas

        # JPEG safety
        if pillow_fmt == "JPEG" and resized.mode in ("RGBA", "LA"):
            resized = resized.convert("RGB")

        buf = BytesIO()
        save_args = {"optimize": True}

        if pillow_fmt in ("JPEG", "WEBP"):
            save_args["quality"] = quality

        resized.save(buf, pillow_fmt, **save_args)
        buf.seek(0)

        base = upload.filename.rsplit(".", 1)[0]
        results.append((f"{sanitize_filename(base)}-resized.{ext}", buf))

    # SINGLE
    if len(results) == 1:
        fn, buf = results[0]
        return StreamingResponse(
            buf,
            media_type=mime,
            headers={
                "Content-Disposition": f'attachment; filename="{fn}"',
                "Content-Length": str(len(buf.getvalue())),
            },
        )

    # ZIP
    zip_buf = BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as z:
        for fn, buf in results:
            z.writestr(fn, buf.getvalue())

    zip_buf.seek(0)
    return StreamingResponse(
        zip_buf,
        media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="resized-images.zip"',
            "Content-Length": str(len(zip_buf.getvalue())),
        },
    )

