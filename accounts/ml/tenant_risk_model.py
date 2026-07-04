import json
import logging
from pathlib import Path

from django.conf import settings

MODEL_PATH = Path(settings.BASE_DIR) / "exports" / "ml" / "tenant_risk_rf.joblib"
METRICS_PATH = Path(settings.BASE_DIR) / "exports" / "ml" / "tenant_risk_rf_metrics.json"
logger = logging.getLogger(__name__)


def model_exists():
    return MODEL_PATH.exists()


def load_model_bundle():
    if not model_exists():
        return None
    try:
        import joblib

        return joblib.load(MODEL_PATH)
    except Exception as exc:
        logger.warning("Tenant risk model could not be loaded from %s: %s", MODEL_PATH, exc)
        return None


def load_model_metrics():
    if not METRICS_PATH.exists():
        return None
    try:
        with open(METRICS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        logger.warning("Tenant risk model metrics could not be loaded from %s: %s", METRICS_PATH, exc)
        return None


def _model_feature_names(bundle, model):
    bundle_features = bundle.get("features") if isinstance(bundle, dict) else None
    if bundle_features:
        return [str(feature) for feature in bundle_features]
    model_features = getattr(model, "feature_names_in_", None)
    if model_features is not None:
        return [str(feature) for feature in model_features]
    return []


def get_model_artifact_status():
    bundle = load_model_bundle()
    metrics = load_model_metrics()
    model = bundle.get("model") if isinstance(bundle, dict) else None
    bundle_version = bundle.get("model_version") if isinstance(bundle, dict) else None
    metrics_version = metrics.get("model_version") if isinstance(metrics, dict) else None
    bundle_features = _model_feature_names(bundle, model) if bundle else []
    metrics_features = [str(feature) for feature in (metrics.get("features") or [])] if isinstance(metrics, dict) else []
    version_match = bool(bundle_version and metrics_version and bundle_version == metrics_version)
    feature_match = bool(bundle_features and metrics_features and bundle_features == metrics_features)

    warnings = []
    if not bundle:
        warnings.append("RF model bundle is missing or unreadable.")
    if not metrics:
        warnings.append("RF metrics file is missing or unreadable.")
    if bundle and metrics and not version_match:
        warnings.append(
            f"RF model version ({bundle_version}) does not match RF metrics version ({metrics_version})."
        )
    if bundle and metrics and not feature_match:
        warnings.append(
            f"RF feature list mismatch: model has {len(bundle_features)} feature(s) while metrics file has {len(metrics_features)}."
        )

    is_consistent = bool(bundle and metrics and version_match and feature_match)
    return {
        "bundle_version": bundle_version,
        "metrics_version": metrics_version,
        "bundle_feature_count": len(bundle_features),
        "metrics_feature_count": len(metrics_features),
        "bundle_features": bundle_features,
        "metrics_features": metrics_features,
        "version_match": version_match,
        "feature_match": feature_match,
        "is_consistent": is_consistent,
        "warnings": warnings,
    }


def _align_features_for_model(bundle, model, X):
    model_features = _model_feature_names(bundle, model)
    if not model_features:
        return X, list(X.columns)

    aligned = X.copy()
    for feature in model_features:
        if feature not in aligned.columns:
            aligned[feature] = 0
    aligned = aligned[model_features]
    return aligned.fillna(0), model_features


def top_feature_signals(model, X, feature_names, limit=3):
    importances = getattr(model, "feature_importances_", None)
    if importances is None:
        return []
    row = X.iloc[0]
    scored = []
    for feature, importance in zip(feature_names, importances):
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
    try:
        from accounts.ml.tenant_risk_features import (
            build_prediction_features_for_tenant,
            risk_probability_to_level,
        )

        bundle = load_model_bundle()
        if not bundle:
            return None
        model = bundle.get("model")
        if not model:
            return None
        X = build_prediction_features_for_tenant(tenant)
        if X is None or X.empty:
            return None
        aligned_X, feature_names = _align_features_for_model(bundle, model, X)
        probability = float(model.predict_proba(aligned_X)[0][1])
        return {
            "probability": round(probability, 4),
            "risk_level": risk_probability_to_level(probability),
            "top_factors": top_feature_signals(model, aligned_X, feature_names),
            "model_version": bundle.get("model_version", ""),
        }
    except Exception as exc:
        logger.warning("Tenant risk prediction failed for tenant %s: %s", getattr(tenant, "id", None), exc)
        return None
