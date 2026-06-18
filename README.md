# Movazzi Clip Finder GPT

A deployable starter kit for a Custom GPT + YouTube Data API backend that finds non-Short YouTube source videos for funny celebrity moments.

## What it does

You type a celebrity name into your Custom GPT, for example:

> Ryan Reynolds

The GPT calls this backend, and the backend:

1. Searches YouTube with multiple query templates.
2. Filters out Shorts and very short videos.
3. Tries to avoid compilations/reuploads.
4. Pulls video metadata: title, channel, duration, views, likes, comments, upload date.
5. Reads top-level comments.
6. Extracts viewer-mentioned timestamps like `2:43`, `5:12`, `1:02:33`.
7. Scores videos by popularity, relevance, official-source signals, and timestamp/comment signals.
8. Returns up to 50 ranked YouTube links with likely key moments.

## Files

- `app/main.py` — FastAPI backend.
- `requirements.txt` — Python dependencies.
- `.env.example` — environment variables.
- `openapi.yaml` — paste/import this into your Custom GPT Action after replacing the server URL.
- `custom_gpt_instructions.md` — paste into the Custom GPT instructions field.
- `setup_guide.md` — full setup steps.

## Important legal/content note

This tool helps you research and locate source videos. It does **not** grant permission to reuse copyrighted footage. You still need to review sources and make sure your use is licensed, permitted, or defensibly transformative/fair use in your jurisdiction.

## Quick local test

```bash
cd movazzi_clip_finder_gpt
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# Add your YOUTUBE_API_KEY and MOVAZZI_ACTION_KEY to .env
uvicorn app.main:app --reload
```

Test:

```bash
curl -H "X-Movazzi-Key: your_secret_key_here" \
"http://127.0.0.1:8000/find-videos?celebrity=Ryan%20Reynolds&limit=10"
```

For Custom GPT Actions, deploy this backend to a public HTTPS URL first.
