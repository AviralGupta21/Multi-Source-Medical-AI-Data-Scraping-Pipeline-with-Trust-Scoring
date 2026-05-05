import re
import logging
from datetime import datetime
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

SEO_SPAM_SIGNALS = [
    r"top\s*\d+\s*(ways|tips|tricks|hacks|secrets)",
    r"you\s+won['\u2019]t\s+believe",
    r"click\s+here",
    r"best\s+\w+\s+ever",
    r"\d+\s+things\s+you",
    r"make\s+money\s+fast",
    r"free\s+(download|access|trial)",
]

PREDATORY_DOMAINS = {
    "ezinearticles.com",
    "hubpages.com",
    "triond.com",
    "helium.com",
    "bukisa.com",
}

VERIFIABLE_LANGUAGES = {"en", "unknown"}

SPAM_PENALTY         = 0.70   
NON_ENGLISH_PENALTY  = 0.85   
PREDATORY_PENALTY    = 0.60  

WEIGHTS = {
    "domain_authority":       0.25,
    "author_credibility":     0.25,
    "recency":                0.20,
    "citation_count":         0.15,
    "medical_disclaimer":     0.15,
}

assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9, "Weights must sum to 1.0"

HIGH_AUTHORITY_DOMAINS = {
    "pubmed.ncbi.nlm.nih.gov",
    "ncbi.nlm.nih.gov",
    "nejm.org",
    "thelancet.com",
    "jamanetwork.com",
    "bmj.com",
    "nature.com",
    "science.org",
    "cell.com",
    "ieee.org",
    "acm.org",
    "arxiv.org",
}

MEDIUM_HIGH_DOMAINS = {
    "towardsdatascience.com",
    "distill.pub",
    "huggingface.co",
    "openai.com",
    "deepmind.com",
    "ai.googleblog.com",
    "research.google",
    "blogs.microsoft.com",
}

LOW_DOMAINS = {
    "medium.com",
    "wordpress.com",
    "blogspot.com",
    "substack.com",
    "reddit.com",
    "quora.com",
}

YOUTUBE_CHANNEL_WHITELIST = {
    "two minute papers",          
    "yannic kilcher",             
    "andrej karpathy",            
    "deepmind",                   
    "google deepmind",
    "mit opencourseware",         
    "stanford university",        
    "lex fridman",                
    "sentdex",                    
    "3blue1brown",                
    "weights & biases",           
}

DISCLAIMER_PATTERNS = [
    r"not intended as medical advice",
    r"consult\s+(a|your)\s+(doctor|physician|healthcare\s+provider|specialist)",
    r"for\s+informational\s+purposes\s+only",
    r"this\s+(article|post|content|video)\s+is\s+not\s+a\s+substitute",
    r"always\s+seek\s+(professional|medical)\s+advice",
    r"disclaimer",
    r"do\s+not\s+use\s+this\s+(article|content)\s+to\s+diagnose",
    r"not\s+a\s+medical\s+professional",
]


def score_domain_authority(source_url: str, source_type: str, channel_name: str = "") -> float:
    if not source_url:
        logger.warning("score_domain_authority: empty URL — returning 0.2")
        return 0.2

    try:
        parsed = urlparse(source_url)
        hostname = parsed.netloc.lower().replace("www.", "")
    except Exception:
        logger.warning(f"score_domain_authority: could not parse URL '{source_url}'")
        return 0.2

    if source_type == "pubmed":
        return 1.0

    tld = "." + hostname.split(".")[-1]
    if tld in (".edu", ".gov", ".ac"):
        return 1.0

    if hostname in HIGH_AUTHORITY_DOMAINS:
        return 0.9

    if hostname in MEDIUM_HIGH_DOMAINS:
        return 0.6

    if "medium.com" in hostname:
        return 0.4

    if source_type == "youtube" or "youtube.com" in hostname or "youtu.be" in hostname:
        if channel_name and channel_name.strip().lower() in YOUTUBE_CHANNEL_WHITELIST:
            logger.debug(
                f"score_domain_authority: '{channel_name}' is whitelisted → 0.70"
            )
            return 0.70
        return 0.35

    if hostname in LOW_DOMAINS:
        return 0.2

    for domain in HIGH_AUTHORITY_DOMAINS:
        if hostname.endswith(domain):
            return 0.9

    logger.debug(f"score_domain_authority: no match for '{hostname}' → 0.2")
    return 0.2


def _score_single_author(author: str) -> float:
    if not author or author.strip().lower() in ("unknown", "", "none"):
        return 0.1

    a = author.strip()

    if "http" in a.lower() or len(a) > 80:
        logger.warning(f"_score_single_author: suspicious author string '{a[:40]}…' → 0.1")
        return 0.1

    digit_ratio = sum(c.isdigit() for c in a) / max(len(a), 1)
    if digit_ratio > 0.3:
        return 0.2

    a_lower = a.lower()

    org_keywords = [
        "office of", "communications", "editorial", "staff", "team",
        "department of", "school of", "centre for", "center for",
    ]
    is_org = any(kw in a_lower for kw in org_keywords)

    institution_signals = [
        "university", "institute", "hospital", "clinic", "college",
        "school", "lab", "research", "md", "phd", "dr.", "prof",
        "m.d.", "ph.d.",
    ]
    has_institution = any(sig in a_lower for sig in institution_signals)

    if is_org:
        return 0.6   

    if has_institution:
        return 0.8   
    
    if re.match(r'^[A-Z][a-zA-Z\-]+,\s+[A-Z][a-zA-Z\s\.]+$', a):
        return 0.8
    
    brand_signals = [
        "startups", "labs", "solutions", "technologies", "media",
        "studio", "academy", "ventures", "inc", "llc", "ltd", "co.",
        "digital", "group", "network", "systems", "services",
    ]
    is_brand = any(kw in a_lower for kw in brand_signals)
    if is_brand:
        return 0.3 
    
    words = a.split()
    if 2 <= len(words) <= 4 and all(w.replace("-", "").replace("'", "").isalpha() for w in words):
        return 0.5   

    return 0.4       


def score_author_credibility(author) -> float:
    if isinstance(author, list):
        if not author:
            return 0.1
        valid = [a for a in author if a and a.strip().lower() not in ("unknown", "")]
        if not valid:
            return 0.1
        scores = [_score_single_author(a) for a in valid]
        avg = sum(scores) / len(scores)
        logger.debug(
            f"score_author_credibility: {len(valid)} authors, avg={avg:.3f}"
        )
        return round(avg, 4)

    return _score_single_author(str(author))


def score_recency(published_date: str) -> float:
    if not published_date or str(published_date).strip().lower() in ("unknown", "", "none"):
        logger.debug("score_recency: unknown date → 0.2")
        return 0.2

    date_str = str(published_date).strip()

    match = re.search(r'\b(19|20)\d{2}\b', date_str)
    if not match:
        logger.warning(f"score_recency: could not parse year from '{date_str}' → 0.2")
        return 0.2

    year = int(match.group())
    current_year = datetime.now().year

    if year > current_year:
        logger.warning(f"score_recency: future year {year} → treating as Unknown")
        return 0.2

    if year >= 2024:
        return 1.0
    elif year >= 2021:
        return 0.7
    elif year >= 2018:
        return 0.5
    elif year >= 2015:
        return 0.3
    else:
        return 0.1


def score_citation_count(
    source_type: str,
    citation_count: int = 0,
    subscriber_count: int = 0,
) -> float:
    import math
    if str(source_type).lower() == "youtube":
        if subscriber_count and subscriber_count > 0:
            if subscriber_count >= 1_000_000:
                score = 0.90
            elif subscriber_count >= 500_000:
                score = 0.75
            elif subscriber_count >= 100_000:
                score = 0.55
            elif subscriber_count >= 10_000:
                score = 0.35
            elif subscriber_count >= 1_000:
                score = 0.20
            else:
                score = 0.10
            logger.debug(
                f"score_citation_count: YouTube subscribers={subscriber_count:,} → {score}"
            )
            return score
        logger.debug("score_citation_count: YouTube with no subscriber data → 0.1")
        return 0.1
    
    if str(source_type).lower() == "pubmed":
        if citation_count and citation_count > 0:
            raw = math.log10(citation_count + 1) / math.log10(1001)
            return round(min(raw, 1.0), 4)
        return 0.9

    if str(source_type).lower() == "blog":
        return 0.4   

    logger.warning(f"score_citation_count: unknown source_type '{source_type}' → 0.1")
    return 0.1


def score_medical_disclaimer(
    content_chunks: list,
    source_type: str,
) -> float:
    if str(source_type).lower() == "pubmed":
        return 0.5

    if not content_chunks:
        return 0.0

    sample_text = " ".join(str(c) for c in content_chunks)[:2000].lower()

    for pattern in DISCLAIMER_PATTERNS:
        if re.search(pattern, sample_text):
            logger.debug(f"score_medical_disclaimer: pattern '{pattern}' matched → 1.0")
            return 1.0

    logger.debug("score_medical_disclaimer: no disclaimer found → 0.0")
    return 0.0


def detect_seo_spam(content_chunks: list, source_url: str) -> bool:
    try:
        hostname = urlparse(source_url).netloc.lower().replace("www.", "")
        if hostname in PREDATORY_DOMAINS:
            logger.warning(f"detect_seo_spam: predatory domain '{hostname}' detected")
            return True
    except Exception:
        pass

    if not content_chunks:
        return False

    sample = " ".join(str(c) for c in content_chunks)[:1000].lower()

    for pattern in SEO_SPAM_SIGNALS:
        if re.search(pattern, sample):
            logger.warning(f"detect_seo_spam: spam pattern '{pattern}' matched")
            return True

    return False


def detect_fake_author(author, source_url: str) -> bool:
    if isinstance(author, list):
        return False

    a = str(author).strip()

    if not a or a.lower() in ("unknown", "none", ""):
        return False   

    if "http" in a.lower() or "@" in a:
        logger.warning(f"detect_fake_author: URL/email in author field → fake")
        return True

    special_ratio = sum(not c.isalpha() and not c.isspace() for c in a) / max(len(a), 1)
    if special_ratio > 0.25:
        logger.warning(f"detect_fake_author: high special char ratio in '{a[:40]}' → fake")
        return True

    try:
        hostname = urlparse(source_url).netloc.lower()
        is_youtube = "youtube" in hostname
    except Exception:
        is_youtube = False

    if not is_youtube and len(a.split()) == 1 and len(a) < 20:
        logger.warning(f"detect_fake_author: single-word author '{a}' on non-YouTube → suspicious")
        return True

    return False


def apply_abuse_penalties(
    trust: float,
    record: dict,
    is_spam: bool,
    is_fake_author: bool,
) -> float:
    language = record.get("language", "en")
    source_url = record.get("source_url", "")

    original = trust

    if is_spam:
        trust *= SPAM_PENALTY
        logger.warning(f"Abuse penalty: SEO spam → ×{SPAM_PENALTY} → {trust:.4f}")

    if is_fake_author:
        trust *= 0.75
        logger.warning(f"Abuse penalty: fake author → ×0.75 → {trust:.4f}")

    if language not in VERIFIABLE_LANGUAGES:
        trust *= NON_ENGLISH_PENALTY
        logger.info(
            f"Non-English content ('{language}') → ×{NON_ENGLISH_PENALTY} → {trust:.4f}"
        )

    try:
        hostname = urlparse(source_url).netloc.lower().replace("www.", "")
        if hostname in PREDATORY_DOMAINS:
            trust *= PREDATORY_PENALTY
            logger.warning(
                f"Abuse penalty: predatory domain '{hostname}' → ×{PREDATORY_PENALTY} → {trust:.4f}"
            )
    except Exception:
        pass

    if trust != original:
        logger.info(f"Total abuse adjustment: {original:.4f} → {trust:.4f}")

    return round(min(max(trust, 0.0), 1.0), 4)


def calculate_trust_score(record: dict) -> float:
    source_url     = record.get("source_url", "")
    source_type    = record.get("source_type", "")
    author         = record.get("author", "Unknown")
    published_date = record.get("published_date", "Unknown")
    content_chunks = record.get("content_chunks", [])
    language       = record.get("language", "en")

    meta             = record.get("_meta", {})
    citation_count   = meta.get("citation_count", 0)
    subscriber_count = meta.get("subscriber_count", 0)
    channel_name     = meta.get("channel_name", "") or (
        author if source_type == "youtube" else ""
    )

    da  = score_domain_authority(source_url, source_type, channel_name)
    ac  = score_author_credibility(author)
    rec = score_recency(published_date)
    cc  = score_citation_count(source_type, citation_count, subscriber_count)
    md  = score_medical_disclaimer(content_chunks, source_type)

    effective_rec = rec if (da >= 0.5 or ac >= 0.6) else rec * 0.5
    if effective_rec != rec:
        logger.debug(
            f"Credibility-aware recency: DA={da:.2f} AC={ac:.2f} "
            f"→ recency halved {rec:.2f} → {effective_rec:.2f}"
        )

    trust = (
        WEIGHTS["domain_authority"]   * da  +
        WEIGHTS["author_credibility"] * ac  +
        WEIGHTS["recency"]            * effective_rec +
        WEIGHTS["citation_count"]     * cc  +
        WEIGHTS["medical_disclaimer"] * md
    )

    trust = round(min(max(trust, 0.0), 1.0), 4)

    logger.info(
        f"Trust score for '{source_url[:60]}': "
        f"DA={da:.2f} AC={ac:.2f} REC={effective_rec:.2f} CC={cc:.2f} MD={md:.2f} → BASE={trust}"
    )

    is_spam        = detect_seo_spam(content_chunks, source_url)
    is_fake_author = detect_fake_author(author, source_url)

    trust = apply_abuse_penalties(trust, record, is_spam, is_fake_author)

    logger.info(f"Final trust score: {trust}")
    return trust


def score_all(records: list[dict]) -> list[dict]:
    for record in records:
        record["trust_score"] = calculate_trust_score(record)
    return records
