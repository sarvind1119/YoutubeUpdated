
from fastapi import FastAPI, Form, Request, Query, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.responses import StreamingResponse, FileResponse
from enum import Enum
from typing import Optional
from app.youtube_client import get_comments
from app.analysis import analyze_comments
import pandas as pd
import uuid
import io
import os
import glob
import time
from collections import defaultdict

app = FastAPI()
templates = Jinja2Templates(directory="app/templates")

class ExportFormat(str, Enum):
    json = "json"
    csv = "csv"
    xlsx = "xlsx"

def extract_video_id(url: str) -> str:
    from urllib.parse import urlparse, parse_qs
    parsed_url = urlparse(url)
    netloc = parsed_url.netloc.lower()
    if "youtu.be" in netloc:
        return parsed_url.path.strip("/")
    if "youtube.com" in netloc:
        return parse_qs(parsed_url.query).get("v", [None])[0]
    return None

def get_top_comments_by_sentiment(comments, count=3):
    sentiment_buckets = defaultdict(list)
    for comment in comments:
        sentiment_buckets[comment['sentiment']].append(comment['text'])
    return {
        sentiment: texts[:count]
        for sentiment, texts in sentiment_buckets.items()
    }

@app.get("/")
async def form_page(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/export")
async def handle_form(
    request: Request,
    video_url: str = Form(...),
    format: ExportFormat = Form(...),
    max_results: Optional[int] = Form(None)
):
    video_id = extract_video_id(video_url)
    if not video_id:
        raise HTTPException(status_code=400, detail="Invalid YouTube URL.")

    comments = get_comments(video_id, max_results=max_results)
    if not comments or "error" in comments:
        raise HTTPException(status_code=500, detail=f"Error fetching comments: {comments.get('error')}")

    analysis = analyze_comments(comments)
    sentiment = analysis["sentiment_distribution"]
    labeled_comments = analysis["labeled_comments"]
    total = len(labeled_comments)
    top_examples = get_top_comments_by_sentiment(labeled_comments)

    df = pd.DataFrame(labeled_comments)

    # Cleanup old temp files older than 5 mins
    now = time.time()
    os.makedirs("temp", exist_ok=True)
    for file in glob.glob("temp/*"):
        if os.path.isfile(file) and now - os.path.getmtime(file) > 300:
            os.remove(file)

    token = str(uuid.uuid4())[:8]
    base = f"temp/{video_id}_{token}"
    df.to_csv(f"{base}.csv", index=False)
    df.to_excel(f"{base}.xlsx", index=False)
    df.to_json(f"{base}.json", orient="records", indent=2)

    download_links = {
        "csv": f"/download/{video_id}_{token}.csv",
        "xlsx": f"/download/{video_id}_{token}.xlsx",
        "json": f"/download/{video_id}_{token}.json"
    }

    return templates.TemplateResponse("index.html", {
        "request": request,
        "video_url": video_url,
        "max_results": max_results,
        "sentiment": sentiment,
        "total_comments": total,
        "download_links": download_links,
        "top_examples": top_examples
    })

@app.get("/download/{filename}")
async def download_file(filename: str):
    filepath = f"temp/{filename}"
    if os.path.exists(filepath):
        return FileResponse(filepath, filename=filename)
    else:
        raise HTTPException(status_code=404, detail="File not found")
