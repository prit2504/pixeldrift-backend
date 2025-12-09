from fastapi import APIRouter, UploadFile, File
from fastapi.responses import StreamingResponse
from rembg import remove
from io import BytesIO
from PIL import Image

router = APIRouter()


### Remove Background ###
@router.post("/remove-background")
async def remove_background(file: UploadFile = File(...)):
    try:
        img_bytes = await file.read()
        input_image = Image.open(BytesIO(img_bytes))

        # Convert unsupported formats
        if input_image.mode == "RGBA":
            input_image = input_image.convert("RGB")

        output_bytes = remove(img_bytes)  # rembg does the removal

        return StreamingResponse(
            BytesIO(output_bytes),
            media_type="image/png",
            headers={
                "Content-Disposition": "attachment; filename=background_removed.png"
            }
        )

    except Exception as e:
        return {"error": "Failed to process image", "details": str(e)}
