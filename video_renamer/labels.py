import re


def sanitize_label(label: str) -> str:
    label = (label or "").lower().strip()
    label = label.replace(" ", "_")
    label = re.sub(r"[^a-z0-9_]", "", label)
    label = re.sub(r"_+", "_", label).strip("_")
    return label or "review_needed"


def clean_optional_label(value) -> str:
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return ""
    return sanitize_label(text)


def tokenize_label(label: str) -> set:
    return {part for part in sanitize_label(label).split("_") if part}


def similarity_score(label1: str, label2: str) -> float:
    left = sanitize_label(label1)
    right = sanitize_label(label2)

    if left == right:
        return 1.0

    if left in right or right in left:
        return 0.9

    left_tokens = tokenize_label(left)
    right_tokens = tokenize_label(right)

    if not left_tokens or not right_tokens:
        return 0.0

    overlap = len(left_tokens & right_tokens)
    union = len(left_tokens | right_tokens)
    return overlap / union if union else 0.0


def labels_are_similar(label1: str, label2: str) -> bool:
    return similarity_score(label1, label2) >= 0.6


def choose_case_label(labels: list[str]) -> str:
    cleaned = [sanitize_label(label) for label in labels if sanitize_label(label) != "review_needed"]
    if not cleaned:
        return "review_needed"
    cleaned = sorted(cleaned, key=lambda value: (len(value), value))
    return cleaned[0]
