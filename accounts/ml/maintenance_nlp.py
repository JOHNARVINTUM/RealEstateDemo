"""
NLP Priority Predictor for Maintenance Requests
Model: TF-IDF feature pipeline + saved classifier bundle
Language: English only (multilingual support is future work)
"""
import os
import logging
import re

logger = logging.getLogger(__name__)

MODEL_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "exports", "ml", "maintenance_nlp.joblib"
)
MODEL_PATH = os.path.normpath(MODEL_PATH)

_model_cache = None


ISSUE_CATEGORY_KEYWORDS = {
    "PLUMBING": [
        "leak", "leaking", "water", "faucet", "sink", "toilet", "flush", "drain",
        "clogged", "pipe", "shower", "bidet", "drainage", "hose",
    ],
    "ELECTRICAL": [
        "electricity", "electric", "outlet", "socket", "wiring", "wire", "power",
        "breaker", "light", "bulb", "switch", "spark", "short circuit", "no power",
    ],
    "STRUCTURAL": [
        "wall", "ceiling", "floor", "crack", "door", "window", "roof", "tile",
        "stairs", "gate", "lock", "knob", "cabinet", "structural", "damage",
    ],
}


def _normalize_text(text):
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _clean_text(text):
    if not text:
        return ""

    normalized = text.lower()
    normalized = re.sub(r"[\r\n\t]+", " ", normalized)
    normalized = re.sub(r"[^a-z0-9\s]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def classify_issue_category(text):
    """
    Rule-based maintenance issue category classifier.
    Returns dict: {category, confidence, matched_keywords}
    - category: PLUMBING / ELECTRICAL / STRUCTURAL / OTHER
    """
    normalized = _clean_text(text)
    if not normalized:
        return {"category": "OTHER", "confidence": 0.0, "matched_keywords": []}

    scores = {}
    matches = {}
    for category, keywords in ISSUE_CATEGORY_KEYWORDS.items():
        matched = [keyword for keyword in keywords if keyword in normalized]
        matches[category] = matched
        scores[category] = len(matched)

    best_category = max(scores, key=scores.get)
    best_score = scores[best_category]
    if best_score <= 0:
        return {"category": "OTHER", "confidence": 0.0, "matched_keywords": []}

    total_matches = sum(scores.values())
    confidence = round(best_score / total_matches, 4) if total_matches else 0.0
    return {
        "category": best_category,
        "confidence": confidence,
        "matched_keywords": matches[best_category],
    }


def _load_model():
    global _model_cache
    if _model_cache is not None:
        return _model_cache
    try:
        import joblib
        if not os.path.exists(MODEL_PATH):
            return None
        _model_cache = joblib.load(MODEL_PATH)
        return _model_cache
    except Exception as e:
        logger.error(f"Failed to load maintenance NLP model: {e}")
        return None


def predict_priority(text):
    """
    Predict priority level from maintenance description text.
    Returns dict: {priority, confidence, available}
    - priority: uses the saved classifier classes from the current bundle
    - confidence: float 0.0-1.0
    - available: False if model not loaded
    """
    model = _load_model()
    if model is None:
        return {"priority": None, "confidence": None, "available": False}

    try:
        cleaned_text = _clean_text(text)
        if not cleaned_text:
            return {"priority": None, "confidence": None, "available": False}

        if "pipeline" in model:
            proba = model["pipeline"].predict_proba([cleaned_text])[0]
            classes = list(model["pipeline"].named_steps["classifier"].classes_)
        else:
            vectorizer = model["vectorizer"]
            classifier = model["classifier"]
            classes = model["classes"]
            X = vectorizer.transform([cleaned_text])
            proba = classifier.predict_proba(X)[0]

        idx = proba.argmax()
        priority = classes[idx]
        confidence = round(float(proba[idx]), 4)
        all_scores = {cls: round(float(p), 4) for cls, p in zip(classes, proba)}

        return {
            "priority": priority,
            "confidence": confidence,
            "available": True,
            "all_scores": all_scores,
        }
    except Exception as e:
        logger.error(f"NLP priority prediction error: {e}")
        return {"priority": None, "confidence": None, "available": False}


def load_metrics():
    """Load saved model metrics for display on admin page."""
    import json
    metrics_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "exports", "ml", "maintenance_nlp_metrics.json"
    )
    metrics_path = os.path.normpath(metrics_path)
    try:
        with open(metrics_path) as f:
            return json.load(f)
    except Exception:
        return None
