import json
from pathlib import Path

import joblib
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, precision_score, recall_score
from sklearn.model_selection import train_test_split

from accounts.ml.tenant_risk_features import FEATURE_COLUMNS, build_training_dataset


class Command(BaseCommand):
    help = "Train the Random Forest tenant late-payment risk classifier"

    def handle(self, *args, **options):
        self.stdout.write("Building tenant risk training dataset...")
        X, y, meta = build_training_dataset()
        total_rows = len(X)
        positive_rows = int(y.sum()) if total_rows else 0
        negative_rows = int(total_rows - positive_rows)

        if total_rows < 20:
            self.stdout.write(self.style.ERROR(f"Not enough training rows: {total_rows}. Need at least 20."))
            return
        if y.nunique() < 2:
            self.stdout.write(self.style.ERROR("Training labels contain only one class. Need both on-time and late/unpaid examples."))
            return

        stratify = y if min(y.value_counts()) >= 2 else None
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=42, stratify=stratify
        )

        model = RandomForestClassifier(
            n_estimators=200,
            max_depth=6,
            min_samples_leaf=2,
            class_weight="balanced",
            random_state=42,
        )
        model.fit(X_train, y_train)
        y_pred = model.predict(X_test)

        metrics = {
            "model_name": "RandomForestClassifier",
            "model_version": timezone.now().strftime("rf-%Y%m%d-%H%M%S"),
            "trained_at": timezone.now().isoformat(),
            "rows": total_rows,
            "positive_late_or_unpaid_rows": positive_rows,
            "negative_on_time_rows": negative_rows,
            "features": FEATURE_COLUMNS,
            "accuracy": round(float(accuracy_score(y_test, y_pred)), 4),
            "precision": round(float(precision_score(y_test, y_pred, zero_division=0)), 4),
            "recall": round(float(recall_score(y_test, y_pred, zero_division=0)), 4),
            "f1": round(float(f1_score(y_test, y_pred, zero_division=0)), 4),
            "confusion_matrix": confusion_matrix(y_test, y_pred).tolist(),
            "feature_importance": [
                {"feature": feature, "importance": round(float(importance), 4)}
                for feature, importance in sorted(
                    zip(FEATURE_COLUMNS, model.feature_importances_),
                    key=lambda item: item[1],
                    reverse=True,
                )
            ],
        }

        output_dir = Path(settings.BASE_DIR) / "exports" / "ml"
        output_dir.mkdir(parents=True, exist_ok=True)
        model_path = output_dir / "tenant_risk_rf.joblib"
        metrics_path = output_dir / "tenant_risk_rf_metrics.json"

        joblib.dump({"model": model, "model_version": metrics["model_version"], "features": FEATURE_COLUMNS}, model_path)
        with open(metrics_path, "w", encoding="utf-8") as f:
            json.dump(metrics, f, indent=2)

        self.stdout.write(self.style.SUCCESS(f"Rows: {total_rows}"))
        self.stdout.write(self.style.SUCCESS(f"Late/unpaid rows: {positive_rows} | On-time rows: {negative_rows}"))
        self.stdout.write(self.style.SUCCESS(f"Accuracy: {metrics['accuracy']}"))
        self.stdout.write(self.style.SUCCESS(f"Precision: {metrics['precision']}"))
        self.stdout.write(self.style.SUCCESS(f"Recall: {metrics['recall']}"))
        self.stdout.write(self.style.SUCCESS(f"F1: {metrics['f1']}"))
        self.stdout.write(self.style.SUCCESS(f"Model saved to {model_path}"))
        self.stdout.write(self.style.SUCCESS(f"Metrics saved to {metrics_path}"))
