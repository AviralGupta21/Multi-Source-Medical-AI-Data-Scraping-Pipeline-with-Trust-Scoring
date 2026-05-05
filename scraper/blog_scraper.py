import os
import time
import json
import logging
import requests
from bs4 import BeautifulSoup
from newspaper import Article
from langdetect import detect, LangDetectException
from utils.chunking import chunk_by_paragraph

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}
REQUEST_TIMEOUT = 15
RATE_LIMIT_DELAY = 2
MIN_CHUNK_WORDS = 50

class BaseBlogScraper:

    SOURCE_TYPE = "blog"

    def fetch_page(self, url: str) -> BeautifulSoup | None:
        try:
            logger.info(f"Fetching: {url}")
            response = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            time.sleep(RATE_LIMIT_DELAY)
            return BeautifulSoup(response.text, "lxml")
        except requests.exceptions.HTTPError as e:
            logger.warning(f"HTTP error for {url}: {e}")
        except requests.exceptions.ConnectionError:
            logger.warning(f"Connection error for {url}")
        except requests.exceptions.Timeout:
            logger.warning(f"Timeout for {url}")
        return None

    def fetch_with_newspaper(self, url: str) -> Article | None:
        try:
            article = Article(url)
            article.download()
            article.parse()
            return article
        except Exception as e:
            logger.warning(f"newspaper3k failed for {url}: {e}")
            return None

    def clean_text(self, text: str) -> str:
        if not text:
            return ""
        text = text.replace("\xa0", " ")
        text = " ".join(text.split())
        return text.strip()

    def chunk_content(self, text: str) -> list[str]:
        return chunk_by_paragraph(text, min_words=MIN_CHUNK_WORDS)

    def detect_language(self, text: str) -> str:
        try:
            return detect(text[:500])
        except LangDetectException:
            logger.warning("Language detection failed — defaulting to 'unknown'")
            return "unknown"

    def build_output(
        self,
        url: str,
        author: str,
        published_date: str,
        language: str,
        region: str,
        content_chunks: list[str],
    ) -> dict:
        return {
            "source_url": url,
            "source_type": self.SOURCE_TYPE,
            "author": author or "Unknown",
            "published_date": published_date or "Unknown",
            "language": language,
            "region": region or "Unknown",
            "topic_tags": [],
            "trust_score": 0.0,
            "content_chunks": content_chunks,
        }

    def extract(self, url: str) -> dict:
        raise NotImplementedError("Subclasses must implement extract()")

class StanfordScraper(BaseBlogScraper):
    def extract(self, url: str) -> dict:
        logger.info("Running StanfordScraper")
        soup = self.fetch_page(url)

        author = "Unknown"
        published_date = "Unknown"
        region = "United States"
        full_text = ""

        if soup:
            author_meta = soup.find("meta", {"name": "article:author"}) or \
                          soup.find("meta", {"property": "article:author"})
            if author_meta:
                author = author_meta.get("content", "Unknown")

            if author == "Unknown":
                byline = soup.find("p", class_=lambda c: c and "author" in c.lower())
                if byline:
                    author = self.clean_text(byline.get_text())

            if author == "Unknown":
                by_tag = soup.find(string=lambda t: t and t.strip().startswith("By "))
                if by_tag:
                    author = self.clean_text(by_tag.strip().replace("By ", ""))

            date_meta = soup.find("meta", {"property": "article:published_time"})
            if date_meta:
                published_date = date_meta.get("content", "Unknown")[:10]

            article_body = soup.find("main") or soup.find("article") or \
                           soup.find("div", {"class": lambda c: c and "article" in c.lower()})

            if article_body:
                for tag in article_body.find_all(
                    ["nav", "footer", "aside", "script", "style", "figure"]
                ):
                    tag.decompose()
                full_text = article_body.get_text(separator="\n\n")
            else:
                logger.warning("Stanford: article body not found — falling back to newspaper3k")
                article = self.fetch_with_newspaper(url)
                if article:
                    full_text = article.text
                    if not author or author == "Unknown":
                        author = ", ".join(article.authors) or "Unknown"
                    if published_date == "Unknown" and article.publish_date:
                        published_date = str(article.publish_date)[:10]

        else:
            logger.warning("Stanford: page fetch failed — using newspaper3k")
            article = self.fetch_with_newspaper(url)
            if article:
                full_text = article.text
                author = ", ".join(article.authors) or "Unknown"
                if article.publish_date:
                    published_date = str(article.publish_date)[:10]

        language = self.detect_language(full_text)
        chunks = self.chunk_content(full_text)

        logger.info(f"Stanford: extracted {len(chunks)} chunks, author='{author}'")
        return self.build_output(url, author, published_date, language, region, chunks)

class TDSScraper(BaseBlogScraper):
    def extract(self, url: str) -> dict:
        logger.info("Running TDSScraper")

        author = "Unknown"
        published_date = "Unknown"
        region = "Unknown"
        full_text = ""

        article = self.fetch_with_newspaper(url)
        if article:
            full_text = article.text
            if article.authors:
                clean_authors = [
                    a for a in article.authors
                    if len(a.split()) <= 5     
                    and "." not in a           
                    and "http" not in a.lower()
                ]
                author = clean_authors[0] if clean_authors else "Unknown"
            if article.publish_date:
                published_date = str(article.publish_date)[:10]

        soup = self.fetch_page(url)
        if soup:
            if author == "Unknown":
                author_meta = soup.find("meta", {"name": "author"}) or \
                              soup.find("meta", {"property": "article:author"})
                if author_meta:
                    author = author_meta.get("content", "Unknown")

            if published_date == "Unknown":
                date_meta = soup.find("meta", {"property": "article:published_time"})
                if date_meta:
                    published_date = date_meta.get("content", "Unknown")[:10]

            if not full_text:
                logger.warning("TDS: newspaper3k returned empty text — using BS4")
                article_body = soup.find("article") or \
                               soup.find("div", {"class": lambda c: c and "post" in c.lower()})
                if article_body:
                    for tag in article_body.find_all(
                        ["nav", "footer", "aside", "script", "style"]
                    ):
                        tag.decompose()
                    full_text = article_body.get_text(separator="\n\n")

        language = self.detect_language(full_text)
        chunks = self.chunk_content(full_text)

        logger.info(f"TDS: extracted {len(chunks)} chunks, author='{author}'")
        return self.build_output(url, author, published_date, language, region, chunks)

class MediumScraper(BaseBlogScraper):
    FALLBACK_HTML_PATH = "scraper/fallbacks/medium_augmented.html"
    def extract(self, url: str) -> dict:
        logger.info("Running MediumScraper")

        author = "Unknown"
        published_date = "Unknown"
        region = "Unknown"
        full_text = ""

        soup = self.fetch_page(url)
        if soup:
            author_meta = soup.find("meta", {"name": "author"})
            if author_meta:
                author = author_meta.get("content", "Unknown")

            date_meta = soup.find("meta", {"property": "article:published_time"})
            if date_meta:
                published_date = date_meta.get("content", "Unknown")[:10]

            article_body = soup.find("article")
            if article_body:
                for tag in article_body.find_all(
                    ["nav", "footer", "aside", "script", "style", "button"]
                ):
                    tag.decompose()
                full_text = article_body.get_text(separator="\n\n")

        if not full_text:
            logger.warning("Medium: live scrape yielded no content — trying newspaper3k")
            article = self.fetch_with_newspaper(url)
            if article and article.text:
                full_text = article.text
                if author == "Unknown":
                    author = ", ".join(article.authors) or "Unknown"
                if published_date == "Unknown" and article.publish_date:
                    published_date = str(article.publish_date)[:10]

        if not full_text:
            logger.warning("Medium: all live attempts failed — loading saved HTML fallback")
            full_text = self._load_fallback_html()

        language = self.detect_language(full_text)
        chunks = self.chunk_content(full_text)

        logger.info(f"Medium: extracted {len(chunks)} chunks, author='{author}'")
        return self.build_output(url, author, published_date, language, region, chunks)

    def _load_fallback_html(self) -> str:
        try:
            with open(self.FALLBACK_HTML_PATH, "r", encoding="utf-8") as f:
                soup = BeautifulSoup(f.read(), "lxml")
                article_body = soup.find("article")
                if article_body:
                    return article_body.get_text(separator="\n\n")
        except FileNotFoundError:
            logger.error(
                f"Fallback HTML not found at {self.FALLBACK_HTML_PATH}. "
                "Save the Medium article HTML manually and place it there."
            )
        except Exception as e:
            logger.error(f"Fallback HTML load failed: {e}")
        return ""
