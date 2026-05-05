import re
import logging
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from nltk.corpus import stopwords
import nltk

logger = logging.getLogger(__name__)

try:
    STOPWORDS = set(stopwords.words("english"))
    STOPWORDS = set(w.lower() for w in STOPWORDS)
except LookupError:
    nltk.download("stopwords", quiet=True)
    STOPWORDS = set(stopwords.words("english"))

MAX_TAGS = 8                
TFIDF_TOP_N = 5             

MEDICAL_AI_KEYWORDS = {
    "deep learning",
    "machine learning",
    "neural network",
    "convolutional neural network",
    "CNN",
    "artificial intelligence",
    "AI",
    "transfer learning",
    "computer vision",
    "image classification",
    "object detection",
    "feature extraction",
    "model",
    "training",
    "inference",
    "prediction",
    "accuracy",
    "benchmark",

    "chest x-ray",
    "x-ray",
    "radiology",
    "radiologist",
    "medical imaging",
    "pneumonia",
    "diagnosis",
    "pathology",
    "lung disease",
    "scan",
    "CT scan",
    "MRI",
    "fundus",
    "retinopathy",
    "mammography",
    "ultrasound",
    "lesion",
    "tumor",
    "cancer",
    "screening",

    "dataset",
    "CheXNet",
    "ResNet",
    "ImageNet",
    "Kermany",
    "Stanford",
    "PubMed",
    "abstract",
    "clinical",
    "healthcare",
    "patient",
    "explainability",
    "Grad-CAM",
    "explainable AI",
    "XAI",
    "generative AI",
    "synthetic data",
    "data augmentation",
}

KEYWORDS_LOWER = {kw.lower(): kw for kw in MEDICAL_AI_KEYWORDS}

def keyword_match(text: str) -> list[str]:
    if not text:
        return []

    text_lower = text.lower()
    matched = []

    for keyword_lower, keyword_canonical in KEYWORDS_LOWER.items():
        pattern = r'\b' + re.escape(keyword_lower) + r'\b'
        if re.search(pattern, text_lower):
            matched.append(keyword_canonical)

    logger.debug(f"Keyword matching: {len(matched)} keywords found")
    return matched

def tfidf_extract(chunks: list[str], top_n: int = TFIDF_TOP_N) -> list[str]:
    valid_chunks = [c for c in chunks if c and len(c.split()) > 3]

    if not valid_chunks:
        logger.debug("TF-IDF: no valid chunks to process")
        return []

    try:
        vectorizer = TfidfVectorizer(
            max_features=50,
            stop_words="english",
            ngram_range=(1, 2),        
            min_df=1,                  
            token_pattern=r'\b[a-zA-Z][a-zA-Z]+\b'  
        )

        tfidf_matrix = vectorizer.fit_transform(valid_chunks)
        feature_names = vectorizer.get_feature_names_out()

        scores = np.asarray(tfidf_matrix.sum(axis=0)).flatten()

        top_indices = scores.argsort()[-top_n:][::-1]
        top_terms = [feature_names[i] for i in top_indices]

        filtered = [
            term for term in top_terms
            if len(term) > 2
            and term.lower() not in STOPWORDS
        ]

        logger.debug(f"TF-IDF: extracted {len(filtered)} terms")
        return filtered

    except Exception as e:
        logger.warning(f"TF-IDF extraction failed: {e}")
        return []

def generate_tags(content_chunks: list[str], max_tags: int = MAX_TAGS) -> list[str]:
    if not content_chunks:
        logger.warning("generate_tags: empty content_chunks — returning []")
        return []

    full_text = " ".join(content_chunks)

    keyword_tags = keyword_match(full_text)

    tfidf_tags = tfidf_extract(content_chunks, top_n=TFIDF_TOP_N)

    seen = set(t.lower() for t in keyword_tags)
    merged_tags = list(keyword_tags)

    for term in tfidf_tags:
        if term.lower() not in seen:
            merged_tags.append(term)
            seen.add(term.lower())

    final_tags = merged_tags[:max_tags]

    logger.info(
        f"generate_tags: {len(keyword_tags)} keyword + "
        f"{len(tfidf_tags)} TF-IDF → {len(final_tags)} final tags"
    )

    return final_tags