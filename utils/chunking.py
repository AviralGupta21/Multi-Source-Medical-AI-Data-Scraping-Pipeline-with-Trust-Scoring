import re
import logging

logger = logging.getLogger(__name__)

MIN_PARAGRAPH_WORDS = 50 
MIN_SENTENCE_WORDS = 5   
MIN_WORD_CHUNK_WORDS = 50
DEFAULT_CHUNK_SIZE = 300

def chunk_by_paragraph(text: str, min_words: int = MIN_PARAGRAPH_WORDS) -> list[str]:
    if not text or not text.strip():
        return []

    raw_chunks = text.split("\n\n")
    chunks = []

    for chunk in raw_chunks:
        cleaned = _clean_chunk(chunk)
        if len(cleaned.split()) >= min_words:
            chunks.append(cleaned)

    if not chunks:
        logger.debug("chunk_by_paragraph: no paragraph breaks found — using sentence fallback")
        chunks = chunk_by_sentence(text, min_words=min_words)

    logger.debug(f"chunk_by_paragraph: {len(chunks)} chunks extracted")
    return chunks

def chunk_by_words(
    text: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    min_words: int = MIN_WORD_CHUNK_WORDS
) -> list[str]:
    if not text or not text.strip():
        return []

    words = text.split()

    if len(words) <= chunk_size:
        cleaned = _clean_chunk(text)
        return [cleaned] if len(cleaned.split()) >= min_words else []

    chunks = []
    for i in range(0, len(words), chunk_size):
        chunk_words = words[i:i + chunk_size]
        chunk = " ".join(chunk_words)
        cleaned = _clean_chunk(chunk)

        if len(cleaned.split()) >= min_words:
            chunks.append(cleaned)

    if len(chunks) >= 2 and len(chunks[-1].split()) < min_words:
        merged = chunks[-2] + " " + chunks[-1]
        chunks = chunks[:-2] + [merged]

    logger.debug(f"chunk_by_words: {len(chunks)} chunks of ~{chunk_size} words")
    return chunks

def chunk_by_sentence(text: str, min_words: int = MIN_SENTENCE_WORDS) -> list[str]:
    if not text or not text.strip():
        return []

    sentence_pattern = re.compile(r'(?<!\w\.\w.)(?<![A-Z][a-z]\.)(?<=\.|\?|\!)\s+(?=[A-Z])')
    raw_sentences = sentence_pattern.split(text)

    chunks = []
    for sentence in raw_sentences:
        cleaned = _clean_chunk(sentence)
        if len(cleaned.split()) >= min_words:
            chunks.append(cleaned)

    if not chunks and text.strip():
        chunks = [_clean_chunk(text)]

    logger.debug(f"chunk_by_sentence: {len(chunks)} sentence chunks")
    return chunks

def _clean_chunk(text: str) -> str:
    if not text:
        return ""
    text = text.replace("\xa0", " ")     
    text = re.sub(r'\s+', ' ', text)     
    return text.strip()