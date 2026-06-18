import math
import os
import re
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx
import isodate
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field

load_dotenv()

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")
MOVAZZI_ACTION_KEY = os.getenv("MOVAZZI_ACTION_KEY", "")
MIN_DURATION_SECONDS = int(os.getenv("MIN_DURATION_SECONDS", "120"))
COMMENT_SAMPLE_PER_VIDEO = int(os.getenv("COMMENT_SAMPLE_PER_VIDEO", "40"))
DEFAULT_REGION_CODE = os.getenv("DEFAULT_REGION_CODE", "US")

YOUTUBE_BASE = "https://www.googleapis.com/youtube/v3"

app = FastAPI(
    title="Movazzi Clip Finder API",
    version="1.0.0",
    description="Finds non-Short YouTube source videos and likely key moments for funny celebrity video research.",
)

TIMESTAMP_RE = re.compile(r"(?<!\d)(?:(\d{1,2}):)?([0-5]?\d):([0-5]\d)(?!\d)")
SHORTS_WORDS = {"#shorts", "ytshorts", "youtube shorts", "shorts"}
COMPILATION_WORDS = {
    "compilation", "compilations", "best moments", "funniest moments",
    "try not to laugh", "tiktok", "shorts compilation", "all funny moments",
}
FUNNY_WORDS = {
    "funny", "hilarious", "laugh", "laughing", "laughed", "awkward", "roast",
    "savage", "iconic", "legendary", "crying", "dying", "dead", "lmao", "lol",
    "comeback", "reaction", "face", "joke", "jokes", "can't stop laughing",
    "😂", "🤣", "💀",
}
ORIGINAL_SOURCE_CHANNEL_HINTS = {
    "bbc", "the graham norton show", "jimmy kimmel", "the tonight show",
    "late night with seth meyers", "the late show", "conan", "team coco",
    "wired", "vanity fair", "gq", "vogue", "netflix", "paramount pictures",
    "universal pictures", "warner bros", "people", "access hollywood",
    "entertainment tonight", "e! news", "variety", "hollywood reporter",
    "buzzfeed celeb", "first we feast", "hot ones", "ladbible", "bbc radio 1",
    "capital fm", "mtv", "abc", "nbc", "cbs", "itv", "james corden",
}


class Moment(BaseModel):
    timestamp: str
    seconds: int
    mentions: int
    sample_comments: List[str] = Field(default_factory=list)


class VideoCandidate(BaseModel):
    rank: int
    score: float
    title: str
    url: str
    video_id: str
    channel_title: str
    published_at: Optional[str] = None
    duration: str
    duration_seconds: int
    view_count: int = 0
    like_count: Optional[int] = None
    comment_count: int = 0
    likely_original_source: bool = False
    likely_compilation_or_reupload: bool = False
    shorts_filtered_reason: Optional[str] = None
    key_moments: List[Moment] = Field(default_factory=list)
    why_good_for_movazzi: List[str] = Field(default_factory=list)
    caution: List[str] = Field(default_factory=list)


class FindVideosResponse(BaseModel):
    celebrity: str
    limit: int
    searched_queries: List[str]
    total_candidates_scanned: int
    results_returned: int
    results: List[VideoCandidate]
    notes: List[str]


async def yt_get(path: str, params: Dict[str, Any]) -> Dict[str, Any]:
    if not YOUTUBE_API_KEY:
        raise HTTPException(status_code=500, detail="Missing YOUTUBE_API_KEY on server.")
    params = dict(params)
    params["key"] = YOUTUBE_API_KEY
    async with httpx.AsyncClient(timeout=25) as client:
        resp = await client.get(f"{YOUTUBE_BASE}/{path}", params=params)
    if resp.status_code != 200:
        detail = resp.text[:1000]
        raise HTTPException(status_code=resp.status_code, detail=f"YouTube API error: {detail}")
    return resp.json()


def require_action_key(x_movazzi_key: Optional[str]) -> None:
    # If MOVAZZI_ACTION_KEY is set, require it.
    if MOVAZZI_ACTION_KEY and x_movazzi_key != MOVAZZI_ACTION_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing X-Movazzi-Key.")


def parse_duration_seconds(iso_duration: str) -> int:
    try:
        return int(isodate.parse_duration(iso_duration).total_seconds())
    except Exception:
        return 0


def format_seconds(seconds: int) -> str:
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def build_queries(celebrity: str) -> List[str]:
    c = celebrity.strip()
    return [
        f'{c} funny interview',
        f'{c} funniest interview',
        f'{c} hilarious interview',
        f'{c} awkward interview',
        f'{c} roast interview',
        f'{c} Graham Norton funny',
        f'{c} Jimmy Fallon funny interview',
        f'{c} Jimmy Kimmel funny interview',
        f'{c} Conan interview funny',
        f'{c} WIRED autocomplete interview funny',
        f'{c} Vanity Fair interview funny',
        f'{c} GQ interview funny',
        f'{c} red carpet funny interview',
        f'{c} Hot Ones funny moments',
    ]


def normalize_text(s: str) -> str:
    return (s or "").lower().strip()

def video_mentions_celebrity(video: Dict[str, Any], celebrity: str) -> bool:
    snippet = video.get("snippet", {})
    title = normalize_text(snippet.get("title", ""))

    celebrity_norm = normalize_text(celebrity)
    tokens = re.findall(r"[a-z0-9]+", celebrity_norm)

    stopwords = {"the", "a", "an", "and", "of", "jr", "sr"}
    tokens = [t for t in tokens if t not in stopwords and len(t) > 1]

    if not tokens:
        return True

    title_tokens = re.findall(r"[a-z0-9]+", title)

    # Strict rule: every meaningful part of the celebrity name must be in the title.
    # Example: "Ryan Reynolds" requires both "ryan" and "reynolds" in the title.
    return all(token in title_tokens for token in tokens)


def is_short_or_bad(video: Dict[str, Any], avoid_shorts: bool) -> Optional[str]:
    snippet = video.get("snippet", {})
    title = normalize_text(snippet.get("title", ""))
    description = normalize_text(snippet.get("description", ""))
    duration_seconds = parse_duration_seconds(video.get("contentDetails", {}).get("duration", ""))

    if not avoid_shorts:
        return None

    combined = f"{title} {description}"
    if any(word in combined for word in SHORTS_WORDS):
        return "Title/description contains Shorts signal."
    if duration_seconds and duration_seconds < MIN_DURATION_SECONDS:
        return f"Duration under minimum threshold ({duration_seconds}s < {MIN_DURATION_SECONDS}s)."
    return None


def detect_compilation(video: Dict[str, Any]) -> bool:
    snippet = video.get("snippet", {})
    title = normalize_text(snippet.get("title", ""))
    channel = normalize_text(snippet.get("channelTitle", ""))
    combined = f"{title} {channel}"
    return any(w in combined for w in COMPILATION_WORDS)


def detect_original_source(video: Dict[str, Any]) -> bool:
    snippet = video.get("snippet", {})
    channel = normalize_text(snippet.get("channelTitle", ""))
    return any(hint in channel for hint in ORIGINAL_SOURCE_CHANNEL_HINTS)


def extract_timestamps_from_comment(text: str) -> List[int]:
    seconds = []
    for match in TIMESTAMP_RE.finditer(text or ""):
        h = int(match.group(1) or 0)
        m = int(match.group(2) or 0)
        s = int(match.group(3) or 0)
        total = h * 3600 + m * 60 + s
        seconds.append(total)
    return seconds


def funny_signal_count(text: str) -> int:
    t = normalize_text(text)
    return sum(1 for w in FUNNY_WORDS if w in t)


async def search_video_ids(
    celebrity: str,
    max_candidates: int,
    region_code: str,
    published_after: Optional[str],
) -> tuple[List[str], List[str]]:
    queries = build_queries(celebrity)
    ids: List[str] = []
    seen = set()

    # Try both relevance and viewCount. ViewCount helps find audience-loved videos.
    orders = ["relevance", "viewCount"]

    for q in queries:
        for order in orders:
            if len(ids) >= max_candidates:
                break
            params = {
                "part": "snippet",
                "q": q,
                "type": "video",
                "maxResults": 25,
                "order": order,
                "safeSearch": "none",
                "videoEmbeddable": "true",
                "regionCode": region_code or DEFAULT_REGION_CODE,
            }
            if published_after:
                params["publishedAfter"] = published_after

            data = await yt_get("search", params)
            for item in data.get("items", []):
                vid = item.get("id", {}).get("videoId")
                if vid and vid not in seen:
                    seen.add(vid)
                    ids.append(vid)
                    if len(ids) >= max_candidates:
                        break

    return ids[:max_candidates], queries


async def fetch_video_details(video_ids: List[str]) -> List[Dict[str, Any]]:
    details: List[Dict[str, Any]] = []
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i:i + 50]
        if not batch:
            continue
        data = await yt_get("videos", {
            "part": "snippet,contentDetails,statistics,status",
            "id": ",".join(batch),
            "maxResults": 50,
        })
        details.extend(data.get("items", []))
    return details


async def fetch_comments(video_id: str, max_comments: int) -> List[str]:
    comments: List[str] = []
    page_token = None

    while len(comments) < max_comments:
        params = {
            "part": "snippet",
            "videoId": video_id,
            "maxResults": min(100, max_comments - len(comments)),
            "textFormat": "plainText",
            "order": "relevance",
        }
        if page_token:
            params["pageToken"] = page_token

        try:
            data = await yt_get("commentThreads", params)
        except HTTPException:
            # Comments may be disabled or unavailable.
            break

        for item in data.get("items", []):
            snippet = item.get("snippet", {}).get("topLevelComment", {}).get("snippet", {})
            text = snippet.get("textDisplay") or snippet.get("textOriginal") or ""
            if text:
                comments.append(text)
                if len(comments) >= max_comments:
                    break

        page_token = data.get("nextPageToken")
        if not page_token:
            break

    return comments


def score_video(video: Dict[str, Any], key_moments: List[Moment], celebrity: str) -> tuple[float, List[str], List[str]]:
    snippet = video.get("snippet", {})
    stats = video.get("statistics", {})
    title = snippet.get("title", "")
    channel = snippet.get("channelTitle", "")
    duration_seconds = parse_duration_seconds(video.get("contentDetails", {}).get("duration", ""))

    views = int(stats.get("viewCount", 0) or 0)
    likes = int(stats.get("likeCount", 0) or 0) if stats.get("likeCount") is not None else 0
    comments = int(stats.get("commentCount", 0) or 0)

    original = detect_original_source(video)
    compilation = detect_compilation(video)

    title_l = normalize_text(title)
    channel_l = normalize_text(channel)
    c_l = normalize_text(celebrity)

    score = 0.0
    score += math.log10(max(views, 1)) * 14
    score += math.log10(max(comments, 1)) * 8
    if likes:
        score += math.log10(max(likes, 1)) * 5

    if c_l and c_l in title_l:
        score += 10
    if any(word in title_l for word in ["funny", "hilarious", "interview", "laugh", "awkward", "roast"]):
        score += 8
    if original:
        score += 18
    if key_moments:
        score += min(30, sum(m.mentions for m in key_moments) * 4)
        score += min(16, len(key_moments) * 4)
    if 180 <= duration_seconds <= 1800:
        score += 6
    if duration_seconds > 3600:
        score -= 6
    if compilation:
        score -= 30
    if any(word in title_l for word in ["shorts", "#shorts", "tiktok"]):
        score -= 50

    why = []
    caution = []

    if views:
        why.append(f"Strong audience signal: {views:,} views.")
    if comments:
        why.append(f"Comment activity: {comments:,} comments.")
    if key_moments:
        why.append(f"Viewer comments mention {len(key_moments)} likely timestamp moment(s).")
    if original:
        why.append("Channel looks like a known original/official source.")
    if "interview" in title_l:
        why.append("Interview format usually works well for voiceover narration.")

    if compilation:
        caution.append("Title/channel suggests this may be a compilation or reupload; verify original source before using.")
    if not original:
        caution.append("Not clearly an official/original source; verify before using.")
    if not key_moments:
        caution.append("No strong timestamp moments found in sampled comments.")

    return round(score, 2), why, caution


def summarize_moments(comments: List[str], duration_seconds: int) -> List[Moment]:
    buckets: Dict[int, List[str]] = defaultdict(list)
    mention_counts = Counter()

    for comment in comments:
        ts_list = extract_timestamps_from_comment(comment)
        signal = funny_signal_count(comment)
        for sec in ts_list:
            if sec <= 0:
                continue
            # Ignore timestamps beyond video duration when duration is known.
            if duration_seconds and sec > duration_seconds + 15:
                continue

            # Bucket timestamps into 10-second windows so 2:43 and 2:48 count together.
            bucket = int(round(sec / 10.0) * 10)
            # Prioritize comments that also contain funny language/emojis.
            weight = 1 + min(signal, 3)
            mention_counts[bucket] += weight
            if len(buckets[bucket]) < 3:
                buckets[bucket].append(comment[:220])

    moments = []
    for sec, count in mention_counts.most_common(8):
        moments.append(Moment(
            timestamp=format_seconds(sec),
            seconds=sec,
            mentions=int(count),
            sample_comments=buckets[sec],
        ))

    return moments


@app.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/find-videos", response_model=FindVideosResponse)
async def find_videos(
    celebrity: str = Query(..., min_length=2, description="Full celebrity name, e.g. Ryan Reynolds."),
    limit: int = Query(50, ge=1, le=50, description="Number of ranked results to return."),
    avoid_shorts: bool = Query(True, description="Filter out YouTube Shorts and very short videos."),
    max_candidates: int = Query(160, ge=25, le=300, description="How many candidate videos to scan before ranking."),
    include_comments: bool = Query(True, description="Whether to scan comments for timestamp clues."),
    region_code: str = Query(DEFAULT_REGION_CODE, min_length=2, max_length=2, description="YouTube region code, e.g. US, GB."),
    published_after: Optional[str] = Query(None, description="Optional RFC3339 date filter, e.g. 2020-01-01T00:00:00Z."),
    x_movazzi_key: Optional[str] = Header(None, alias="X-Movazzi-Key"),
) -> FindVideosResponse:
    require_action_key(x_movazzi_key)

    video_ids, queries = await search_video_ids(
        celebrity=celebrity,
        max_candidates=max_candidates,
        region_code=region_code,
        published_after=published_after,
    )
    details = await fetch_video_details(video_ids)

    candidates: List[VideoCandidate] = []

    for video in details:
        bad_reason = is_short_or_bad(video, avoid_shorts=avoid_shorts)
        if bad_reason:
            continue

        if not video_mentions_celebrity(video, celebrity):
            continue

        snippet = video.get("snippet", {})
        stats = video.get("statistics", {})
        content = video.get("contentDetails", {})
        status = video.get("status", {})

        # Skip videos that are not embeddable/public where possible.
        if status.get("privacyStatus") not in (None, "public"):
            continue

        duration_seconds = parse_duration_seconds(content.get("duration", ""))
        comments_text = []
        moments: List[Moment] = []

        if include_comments and int(stats.get("commentCount", 0) or 0) > 0:
            comments_text = await fetch_comments(video.get("id"), COMMENT_SAMPLE_PER_VIDEO)
            moments = summarize_moments(comments_text, duration_seconds)

        score, why, caution = score_video(video, moments, celebrity)

        like_count = None
        if stats.get("likeCount") is not None:
            try:
                like_count = int(stats.get("likeCount"))
            except Exception:
                like_count = None

        candidates.append(VideoCandidate(
            rank=0,
            score=score,
            title=snippet.get("title", ""),
            url=f"https://www.youtube.com/watch?v={video.get('id')}",
            video_id=video.get("id"),
            channel_title=snippet.get("channelTitle", ""),
            published_at=snippet.get("publishedAt"),
            duration=format_seconds(duration_seconds),
            duration_seconds=duration_seconds,
            view_count=int(stats.get("viewCount", 0) or 0),
            like_count=like_count,
            comment_count=int(stats.get("commentCount", 0) or 0),
            likely_original_source=detect_original_source(video),
            likely_compilation_or_reupload=detect_compilation(video),
            key_moments=moments,
            why_good_for_movazzi=why,
            caution=caution,
        ))

    candidates.sort(key=lambda x: x.score, reverse=True)
    candidates = candidates[:limit]

    for i, candidate in enumerate(candidates, start=1):
        candidate.rank = i

    notes = [
        "This tool ranks research candidates; it does not guarantee reuse rights or fair use.",
        "Always manually verify original source, context, and licensing before using clips.",
        "Key moments are inferred mainly from viewer timestamp comments, not full video understanding.",
        "Shorts are filtered by duration and title/description signals, but verify manually.",
    ]

    return FindVideosResponse(
        celebrity=celebrity,
        limit=limit,
        searched_queries=queries,
        total_candidates_scanned=len(details),
        results_returned=len(candidates),
        results=candidates,
        notes=notes,
    )
    
@app.get("/find-videos-simple")
async def find_videos_simple(
    celebrity: str = Query(..., min_length=2, description="Full celebrity name, e.g. Ryan Reynolds."),
    limit: int = Query(5, ge=1, le=20, description="Number of ranked results to return."),
    avoid_shorts: bool = Query(True, description="Filter out YouTube Shorts and very short videos."),
    max_candidates: int = Query(40, ge=25, le=80, description="How many candidate videos to scan before ranking."),
    include_comments: bool = Query(False, description="Whether to scan comments for timestamp clues."),
    region_code: str = Query(DEFAULT_REGION_CODE, min_length=2, max_length=2, description="YouTube region code, e.g. US, GB."),
    published_after: Optional[str] = Query(None, description="Optional RFC3339 date filter, e.g. 2020-01-01T00:00:00Z."),
    x_movazzi_key: Optional[str] = Header(None, alias="X-Movazzi-Key"),
) -> Dict[str, Any]:
    full_response = await find_videos(
        celebrity=celebrity,
        limit=limit,
        avoid_shorts=avoid_shorts,
        max_candidates=max_candidates,
        include_comments=include_comments,
        region_code=region_code,
        published_after=published_after,
        x_movazzi_key=x_movazzi_key,
    )

    simple_results = []

    for video in full_response.results:
        moments = []
        for moment in video.key_moments[:5]:
            moments.append({
                "timestamp": moment.timestamp,
                "mentions": moment.mentions,
            })

        simple_results.append({
            "rank": video.rank,
            "title": video.title,
            "url": video.url,
            "channel": video.channel_title,
            "duration": video.duration,
            "views": video.view_count,
            "likely_original_source": video.likely_original_source,
            "likely_compilation_or_reupload": video.likely_compilation_or_reupload,
            "key_moments": moments,
            "why_good": video.why_good_for_movazzi[:3],
            "caution": video.caution[:3],
        })

    return {
        "celebrity": full_response.celebrity,
        "results_returned": full_response.results_returned,
        "results": simple_results,
        "notes": [
            "Research candidates only.",
            "Verify original source, context, and reuse rights before using clips.",
            "Shorts are filtered by duration and Shorts signals, but verify manually."
        ],
    }
