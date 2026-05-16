import json
from pathlib import Path

import joblib
from django.conf import settings

from accounts.ml.tenant_risk_features import (
    FEATURE_COLUMNS,
    build_prediction_features_for_tenant,
    risk_probability_to_level,
)

MODEL_PATH = Path(settings.BASE_DIR) / "exports" / "ml" / "tenant_risk_rf.joblib"
METRICS_PATH = Path(settings.BASE_DIR) / "exports" / "ml" / "tenant_risk_rf_metrics.json"


def model_exists():
    return MODEL_PATH.exists()


def load_model_bundle():
    if not model_exists():
        return None
    return joblib.load(MODEL_PATH)


def load_model_metrics():
    if not METRICS_PATH.exists():
        return None
    with open(METRICS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def top_feature_signals(model, X, limit=3):
    importances = getattr(model, "feature_importances_", None)
    if importances is None:
        return []
    row = X.iloc[0]
    scored = []
    for feature, importance in zip(FEATURE_COLUMNS, importances):
        value = row.get(feature, 0)
        if value == 0:
            continue
        scored.append({
            "feature": feature,
            "value": round(float(value), 2),
            "importance": round(float(importance), 4),
        })
    scored.sort(key=lambda item: item["importance"], reverse=True)
    return scored[:limit]


def predict_tenant_risk(tenant):
    bundle = load_model_bundle()
    if not bundle:
        return None
    model = bundle.get("model")
    if not model:
        return None
    X = build_prediction_features_for_tenant(tenant)
    if X is None or X.empty:
        return None
    probability = float(model.predict_proba(X)[0][1])
    return {
        "probability": round(probability, 4),
        "risk_level": risk_probability_to_level(probability),
        "top_factors": top_feature_signals(model, X),
        "model_version": bundle.get("model_version", ""),
    }
