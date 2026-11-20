"""Pure text change measures for annual-report sections."""
import math
import re
from collections import Counter


TOKEN = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    """Lowercase text, retaining the words and numbers used in SEC prose."""
    return TOKEN.findall(text.lower())


def cosine_similarity(current: str, prior: str) -> float:
    """Cosine similarity of plain bag-of-word vectors."""
    left, right = Counter(tokenize(current)), Counter(tokenize(prior))
    if not left or not right:
        return 0.0
    shared = set(left) & set(right)
    dot = sum(left[word] * right[word] for word in shared)
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    similarity = dot / (left_norm * right_norm) if left_norm and right_norm else 0.0
    return 1.0 if abs(similarity - 1.0) < 1e-12 else similarity


def tfidf_similarity(current: str, prior: str) -> float:
    """Cosine similarity over TF-IDF vectors for two documents."""
    left, right = tokenize(current), tokenize(prior)
    if not left or not right:
        return 0.0
    vocabulary = sorted(set(left) | set(right))
    document_frequency = {word: int(word in set(left)) + int(word in set(right)) for word in vocabulary}
    left_count, right_count = Counter(left), Counter(right)
    left_vector = {}
    right_vector = {}
    for word in vocabulary:
        idf = math.log((1 + 2) / (1 + document_frequency[word])) + 1
        left_vector[word] = (left_count[word] / len(left)) * idf
        right_vector[word] = (right_count[word] / len(right)) * idf
    dot = sum(left_vector[word] * right_vector[word] for word in vocabulary)
    left_norm = math.sqrt(sum(value * value for value in left_vector.values()))
    right_norm = math.sqrt(sum(value * value for value in right_vector.values()))
    return dot / (left_norm * right_norm) if left_norm and right_norm else 0.0


def measure_changes(current: str, prior: str, method: str = "tfidf") -> dict[str, float | str]:
    """Return similarity and the host-facing share of text that is new."""
    similarity = tfidf_similarity(current, prior) if method == "tfidf" else cosine_similarity(current, prior)
    similarity = max(0.0, min(1.0, similarity))
    return {
        "method": method,
        "similarity": similarity,
        "new_text_share": 1.0 - similarity,
    }
