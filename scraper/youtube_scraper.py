import os
import json
import logging
import time
from dotenv import load_dotenv
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    TranscriptsDisabled,
    NoTranscriptFound,
    VideoUnavailable,
)
from langdetect import detect, LangDetectException
from utils.chunking import chunk_by_words, chunk_by_sentence

load_dotenv()
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")

if not YOUTUBE_API_KEY:
    raise EnvironmentError(
        "YOUTUBE_API_KEY not found. "
        "Create a .env file with: YOUTUBE_API_KEY=your_key_here"
    )

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

TRANSCRIPT_CHUNK_WORDS = 300   
RATE_LIMIT_DELAY = 1            

class YouTubeScraper:
    SOURCE_TYPE = "youtube"

    def __init__(self):
        self.youtube = build(
            "youtube", "v3",
            developerKey=YOUTUBE_API_KEY
        )
        logger.info("YouTube Data API client initialized")

    def _validate_publish_date(self, date_str: str) -> str:
        from datetime import date
        try:
            parsed = date.fromisoformat(date_str)
            if parsed >= date.today():
                logger.warning(
                    f"Publish date '{date_str}' is today or future "
                    f"— likely an upload timestamp, treating as Unknown"
                )
                return "Unknown"
            return date_str
        except ValueError:
            logger.warning(f"Could not parse date '{date_str}' — treating as Unknown")
            return "Unknown"

    def fetch_metadata(self, video_id: str) -> dict:
        try:
            logger.info(f"Fetching metadata for video ID: {video_id}")
            response = self.youtube.videos().list(
                part="snippet",
                id=video_id
            ).execute()

            time.sleep(RATE_LIMIT_DELAY)

            if not response.get("items"):
                logger.warning(f"No metadata found for video ID: {video_id}")
                return {}

            snippet = response["items"][0]["snippet"]
            return {
                "title": snippet.get("title", "Unknown"),
                "channel": snippet.get("channelTitle", "Unknown"),
                "channel_id": snippet.get("channelId", ""),
                "published_date": snippet.get("publishedAt", "Unknown")[:10],
                "description": snippet.get("description", ""),
                "default_language": snippet.get("defaultLanguage", "unknown"),
                "default_audio_language": snippet.get("defaultAudioLanguage", "unknown"),
            }

        except HttpError as e:
            logger.error(f"YouTube API HTTP error for {video_id}: {e}")
            return {}
        except Exception as e:
            logger.error(f"Unexpected error fetching metadata for {video_id}: {e}")
            return {}
    
    def fetch_channel_stats(self, channel_id: str) -> dict:
        if not channel_id:
            logger.warning("fetch_channel_stats: no channel_id provided — returning 0")
            return {"subscriber_count": 0}

        try:
            logger.info(f"Fetching channel stats for channel ID: {channel_id}")
            response = self.youtube.channels().list(
                part="statistics",
                id=channel_id
            ).execute()

            time.sleep(RATE_LIMIT_DELAY)
            
            if not response.get("items"):
                logger.warning(f"No channel stats found for channel ID: {channel_id}")
                return {"subscriber_count": 0}

            stats = response["items"][0].get("statistics", {})

            if stats.get("hiddenSubscriberCount", False):
                logger.info(f"Channel {channel_id} has hidden subscriber count → 0")
                return {"subscriber_count": 0}

            raw = stats.get("subscriberCount", "0")
            subscriber_count = int(raw) if str(raw).isdigit() else 0

            logger.info(f"Channel {channel_id}: {subscriber_count:,} subscribers")
            return {"subscriber_count": subscriber_count}

        except HttpError as e:
            logger.error(f"YouTube API HTTP error fetching channel stats {channel_id}: {e}")
            return {"subscriber_count": 0}
        except Exception as e:
            logger.error(f"Unexpected error fetching channel stats {channel_id}: {e}")
            return {"subscriber_count": 0}

    def fetch_transcript(self, video_id: str) -> tuple[str, str]:
        try:
            transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
            try:
                transcript = transcript_list.find_manually_created_transcript(['en'])
            except Exception:
                transcript = transcript_list.find_generated_transcript(['en'])
                
            fetched = transcript.fetch()
            text = " ".join(entry["text"] for entry in fetched)
            logger.info(f"Video {video_id}: transcript fetched successfully")
            return text, "fetched"

        except TranscriptsDisabled:
            logger.warning(f"Video {video_id}: transcripts disabled")
            return "", "none"
        except NoTranscriptFound:
            logger.warning(f"Video {video_id}: no transcript found")
            return "", "none"
        except VideoUnavailable:
            logger.warning(f"Video {video_id}: video unavailable")
            return "", "none"
        except Exception as e:
            logger.warning(f"Video {video_id}: transcript failed ({e}) — falling back to description")
            return "", "none"

    def chunk_transcript(self, text: str) -> list[str]:
        return chunk_by_words(text, chunk_size=TRANSCRIPT_CHUNK_WORDS)

    def chunk_description(self, description: str) -> list[str]:
        return chunk_by_sentence(description, min_words=20)

    def detect_language(self, text: str) -> str:
        try:
            return detect(text[:500])
        except LangDetectException:
            return "unknown"

    def extract(self, video_id: str, url: str) -> dict:
        logger.info(f"━━━ Extracting YouTube video: {video_id} ━━━")

        metadata = self.fetch_metadata(video_id)

        author = metadata.get("channel", "Unknown")
        channel_id = metadata.get("channel_id", "")
        published_date = metadata.get("published_date", "Unknown")
        description = metadata.get("description", "")
        title = metadata.get("title", "Unknown")

        channel_stats = self.fetch_channel_stats(channel_id)
        subscriber_count = channel_stats.get("subscriber_count", 0)

        logger.info(f"Metadata — title='{title}', channel='{author}', date='{published_date}'")

        transcript_text, transcript_source = self.fetch_transcript(video_id)

        if transcript_text:
            content_text = transcript_text
            content_source = transcript_source
            chunks = self.chunk_transcript(transcript_text)
            logger.info(
                f"Video {video_id}: using {transcript_source} transcript "
                f"→ {len(chunks)} chunks"
            )
        else:
            logger.warning(
                f"Video {video_id}: no transcript available — "
                f"falling back to video description"
            )
            content_text = description
            content_source = "description_fallback"
            chunks = self.chunk_description(description)
            logger.info(
                f"Video {video_id}: using description fallback "
                f"→ {len(chunks)} chunks"
            )

        language = self.detect_language(content_text)

        return {
            "source_url": url,
            "source_type": self.SOURCE_TYPE,
            "author": author,
            "published_date": published_date,
            "language": language,
            "region": "Unknown",       
            "topic_tags": [],         
            "trust_score": 0.0,          
            "content_chunks": chunks,
            "_meta": {
                "video_id": video_id,
                "title": title,
                "channel_name": author,
                "subscriber_count": subscriber_count,
                "content_source": content_source,
                "description": description[:500],
            }
        }