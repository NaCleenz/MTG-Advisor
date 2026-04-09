import os
import uvicorn
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional

from recommender import get_recommendations

app = FastAPI(title="MTG Commander Advisor", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class RecommendRequest(BaseModel):
    deck_list: str
    problem_statement: Optional[str] = None


@app.post("/api/recommend")
async def recommend(request: RecommendRequest):
    if not request.deck_list.strip():
        raise HTTPException(status_code=400, detail="Deck list cannot be empty.")
    try:
        result = await get_recommendations(request.deck_list, request.problem_statement or None)
        if "error" in result:
            raise HTTPException(status_code=422, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")


@app.get("/api/health")
async def health():
    from ollama_client import is_ai_available
    return {"status": "ok", "ai": is_ai_available()}


# Serve the frontend locally — skipped on Railway where frontend/ doesn't exist
_frontend = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.isdir(_frontend):
    app.mount("/", StaticFiles(directory=_frontend, html=True), name="frontend")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=False)
