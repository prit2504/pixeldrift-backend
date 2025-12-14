from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routes.pdf_routes import router as pdf_router
from routes.image_routes import router as image_router

app = FastAPI(title="PDF/Image Tools API")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "https://pixeldrift-one.vercel.app/",
        "https://pixeldrift-one.vercel.app"
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routes
app.include_router(pdf_router, prefix="/pdf", tags=["PDF Tools"])
app.include_router(image_router, prefix="/image", tags=["Image Tools"])
@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "message": "Backend is awake"
    }


