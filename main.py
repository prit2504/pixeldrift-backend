from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routes.pdf_routes import router as pdf_router
from routes.image_routes import router as image_router
from routes.ai_routes import router as ai_router

app = FastAPI(title="PDF/Image Tools API")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # update later
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routes
app.include_router(pdf_router, prefix="/pdf", tags=["PDF Tools"])
app.include_router(image_router, prefix="/image", tags=["Image Tools"])

app.include_router(ai_router, prefix="/ai", tags=["AI Tools"])


# if __name__ == "__main__":
#     import uvicorn
#     uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
