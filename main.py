import json
import os
import logging

from scraper.blog_scraper import StanfordScraper, TDSScraper, MediumScraper
from scraper.youtube_scraper import YouTubeScraper
from scraper.pubmed_scraper import PubMedScraper

from utils.tagging import generate_tags
from scoring.trust_score import calculate_trust_score

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def load_sources():
    with open("sources.json", "r", encoding="utf-8") as f:
        return json.load(f)

def get_blog_scraper(scraper_type):
    if scraper_type == "stanford":
        return StanfordScraper()
    elif scraper_type == "tds":
        return TDSScraper()
    return MediumScraper()

def process_blog(source):
    scraper = get_blog_scraper(source["type"])
    return scraper.extract(source["url"])

def process_youtube(source, scraper):
    video_id = source["video_id"]
    url = source["url"]   
    return scraper.extract(video_id, url)

def process_pubmed(source, scraper):
    pmid = source["pmid"]
    url = source["url"]   
    return scraper.extract(pmid, url)

def enrich(record):
    record["topic_tags"] = generate_tags(record["content_chunks"])
    record["trust_score"] = calculate_trust_score(record)
    return record

def main():
    sources = load_sources()
    results = []

    yt_scraper = YouTubeScraper()
    pm_scraper = PubMedScraper()

    for blog in sources.get("blogs", []):
        try:
            logger.info(f"Processing blog: {blog.get('label', blog['url'])}")
            record = process_blog(blog)
            results.append(enrich(record))
        except Exception as e:
            logger.error(f"Blog failed: {blog.get('label', blog)} → {e}")

    for yt in sources.get("youtube", []):
        try:
            logger.info(f"Processing YouTube: {yt.get('label', yt['video_id'])}")
            record = process_youtube(yt, yt_scraper)
            results.append(enrich(record))
        except Exception as e:
            logger.error(f"YouTube failed: {yt.get('label', yt)} → {e}")

    for pm in sources.get("pubmed", []):
        try:
            logger.info(f"Processing PubMed: {pm.get('label', pm['pmid'])}")
            record = process_pubmed(pm, pm_scraper)
            results.append(enrich(record))
        except Exception as e:
            logger.error(f"PubMed failed: {pm.get('label', pm)} → {e}")

    os.makedirs("output", exist_ok=True)

    with open("output/scraped_data.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    logger.info(f"Saved {len(results)} records → output/scraped_data.json")

if __name__ == "__main__":
    main()