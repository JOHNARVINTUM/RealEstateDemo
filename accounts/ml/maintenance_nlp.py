"""
NLP Priority Predictor for Maintenance Requests
Model: TF-IDF vectorizer + Logistic Regression
Language: English only (multilingual support is future work)
"""
import os
import logging

logger = logging.getLogger(__name__)

MODEL_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "exports", "ml", "maintenance_nlp.joblib"
)
MODEL_PATH = os.path.normpath(MODEL_PATH)

_model_cache = None


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
    - priority: LOW / MEDIUM / HIGH / URGENT
    - confidence: float 0.0-1.0
    - available: False if model not loaded
    """
    model = _load_model()
    if model is None:
        return {"priority": None, "confidence": None, "available": False}

    try:
        vectorizer = model["vectorizer"]
        classifier = model["classifier"]
        classes = model["classes"]

        X = vectorizer.transform([text])
        proba = classifier.predict_proba(X)[0]
        idx = proba.argmax()
        priority = classes[idx]
        confidence = round(float(proba[idx]), 4)

        return {
            "priority": priority,
            "confidence": confidence,
            "available": True,
            "all_scores": {cls: round(float(p), 4) for cls, p in zip(classes, proba)},
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
