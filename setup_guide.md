# Setup Guide: Movazzi Clip Finder GPT

## 1. Get a YouTube Data API key

1. Go to Google Cloud Console.
2. Create or select a project.
3. Enable **YouTube Data API v3**.
4. Create an API key.
5. Keep this key private.

## 2. Prepare the backend

Install Python 3.11+.

```bash
cd movazzi_clip_finder_gpt
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env`:

```env
YOUTUBE_API_KEY=your_google_youtube_data_api_key
MOVAZZI_ACTION_KEY=create_a_long_random_secret
MIN_DURATION_SECONDS=120
COMMENT_SAMPLE_PER_VIDEO=40
DEFAULT_REGION_CODE=US
```

Run locally:

```bash
uvicorn app.main:app --reload
```

Test:

```bash
curl -H "X-Movazzi-Key: create_a_long_random_secret" \
"http://127.0.0.1:8000/find-videos?celebrity=Ryan%20Reynolds&limit=10"
```

## 3. Deploy the backend

Use a host that gives you a public HTTPS URL, such as Render, Railway, Fly.io, or a VPS.

Typical start command:

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

Environment variables to set on the host:

```env
YOUTUBE_API_KEY=your_google_youtube_data_api_key
MOVAZZI_ACTION_KEY=create_a_long_random_secret
MIN_DURATION_SECONDS=120
COMMENT_SAMPLE_PER_VIDEO=40
DEFAULT_REGION_CODE=US
```

## 4. Update the OpenAPI schema

Open `openapi.yaml`.

Replace:

```yaml
servers:
  - url: https://YOUR-DEPLOYED-BACKEND-URL.com
```

with your real deployed backend URL, for example:

```yaml
servers:
  - url: https://movazzi-clip-finder.onrender.com
```

## 5. Create the Custom GPT

1. Open ChatGPT.
2. Create a new GPT.
3. Name it: **Movazzi Clip Finder**.
4. Paste the contents of `custom_gpt_instructions.md` into the Instructions field.
5. Enable Actions.
6. Import/paste the updated `openapi.yaml`.
7. Configure API key authentication:
   - Auth type: API Key
   - Header name: `X-Movazzi-Key`
   - Value: your `MOVAZZI_ACTION_KEY`
8. Test with:

```text
Find 50 original non-Short YouTube source videos for Ryan Reynolds funny moments.
```

## 6. Recommended usage

Use prompts like:

```text
Ryan Reynolds
```

```text
Find 50 non-Short original source videos for Zendaya funny moments. Prioritize interviews and red carpet clips.
```

```text
Find 30 Kevin Hart videos, avoid compilations, and only show videos longer than 3 minutes.
```

## 7. Limits and improvement ideas

### Current limits

- It does not watch videos visually.
- It infers key moments mostly from comments with timestamps.
- It cannot guarantee every source is truly original.
- It cannot guarantee copyright/fair-use safety.
- YouTube API quota limits apply.

### Strong next upgrades

1. Add Google Sheets export.
2. Add transcript analysis for videos you own, license, or have permission to process.
3. Add a whitelist of official channels.
4. Add duplicate detection by title similarity.
5. Add “already used in Movazzi” tracking.
6. Add an output column for suggested voiceover narration angle.
