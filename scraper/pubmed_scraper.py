import os
import json
import logging
import time
from Bio import Entrez, Medline
from langdetect import detect, LangDetectException
from utils.chunking import chunk_by_sentence

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

Entrez.email = os.getenv("NCBI_EMAIL", "your_email@example.com")
Entrez.tool = "DataScrapingAssignment"   

RATE_LIMIT_DELAY = 1        
MIN_SENTENCE_WORDS = 5      

class PubMedScraper:
    SOURCE_TYPE = "pubmed"

    def fetch_record(self, pmid: str) -> dict:
        try:
            logger.info(f"Fetching PubMed record for PMID: {pmid}")

            handle = Entrez.efetch(
                db="pubmed",
                id=pmid,
                rettype="medline",
                retmode="text"
            )

            records = list(Medline.parse(handle))
            handle.close()

            time.sleep(RATE_LIMIT_DELAY) 

            if not records:
                logger.warning(f"No record found for PMID: {pmid}")
                return {}

            record = records[0]
            logger.info(f"Successfully fetched PMID {pmid}: '{record.get('TI', 'Unknown title')}'")
            return record

        except Exception as e:
            logger.error(f"Entrez fetch failed for PMID {pmid}: {e}")
            return {}

    def parse_authors(self, record: dict) -> list[str]:
        full_authors = record.get("FAU", [])
        if full_authors:
            return full_authors

        abbrev_authors = record.get("AU", [])
        if abbrev_authors:
            return abbrev_authors

        logger.warning("No author information found in record")
        return ["Unknown"]

    def parse_published_date(self, record: dict) -> str:
        dp = record.get("DP", "")
        if dp:
            year = dp.split()[0] if dp else "Unknown"
            return year
        return "Unknown"

    def parse_abstract(self, record: dict) -> str:
        abstract = record.get("AB", "")
        if not abstract:
            logger.warning("No abstract found in record — content_chunks will be empty")
        return abstract

    def parse_journal(self, record: dict) -> str:
        return record.get("JT", record.get("TA", "Unknown"))

    def parse_citation_count(self, record: dict) -> int:
        return 0

    def chunk_abstract(self, abstract: str) -> list[str]:
        return chunk_by_sentence(abstract, min_words=MIN_SENTENCE_WORDS)

    def detect_language(self, text: str) -> str:
        try:
            return detect(text[:500])
        except LangDetectException:
            return "unknown"

    def extract(self, pmid: str, url: str) -> dict:
        logger.info(f"━━━ Extracting PubMed article PMID: {pmid} ━━━")

        record = self.fetch_record(pmid)

        if not record:
            logger.error(f"Failed to fetch PMID {pmid} — returning empty record")
            return self._empty_record(url)

        title = record.get("TI", "Unknown")
        authors = self.parse_authors(record)          
        published_date = self.parse_published_date(record)
        abstract = self.parse_abstract(record)
        journal = self.parse_journal(record)
        pub_types = record.get("PT", [])              

        logger.info(f"Title: '{title}'")
        logger.info(f"Authors: {len(authors)} authors found")
        logger.info(f"Journal: {journal}")
        logger.info(f"Published: {published_date}")

        chunks = self.chunk_abstract(abstract)
        logger.info(f"Abstract chunked into {len(chunks)} sentences")

        language = self.detect_language(abstract)

        return {
            "source_url": url,
            "source_type": self.SOURCE_TYPE,
            "author": authors,         
            "published_date": published_date,
            "language": language,
            "region": "United States", 
            "topic_tags": [], 
            "trust_score": 0.0,
            "content_chunks": chunks,
            "_meta": {
                "pmid": pmid,
                "title": title,
                "journal": journal,
                "publication_types": pub_types,
                "author_count": len(authors),
                "abstract_length": len(abstract.split()) if abstract else 0,
                "citation_count": self.parse_citation_count(record),
            }
        }

    def _empty_record(self, url: str) -> dict:
        return {
            "source_url": url,
            "source_type": self.SOURCE_TYPE,
            "author": ["Unknown"],
            "published_date": "Unknown",
            "language": "unknown",
            "region": "Unknown",
            "topic_tags": [],
            "trust_score": 0.0,
            "content_chunks": [],
            "error": "Failed to fetch PubMed record",
        }