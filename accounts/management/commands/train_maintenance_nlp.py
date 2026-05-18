"""
Management command: train_maintenance_nlp
Trains a TF-IDF + Logistic Regression model to predict
maintenance request priority from description text.

Usage:
    python manage.py train_maintenance_nlp
"""
import json
import os

from django.core.management.base import BaseCommand


URGENCY_KEYWORDS = {
    "URGENT": [
        "sparks", "fire", "flood", "flooding", "burst", "danger", "emergency",
        "electric shock", "gas leak", "no electricity", "completely flooded",
        "severe leak", "burning smell", "smoke", "exposed wire",
    ],
    "HIGH": [
        "broken", "not working", "no water", "tripping", "damaged", "collapsed",
        "crack", "ceiling leak", "power outage", "outlet not working",
        "completely broken", "major", "serious", "bad",
    ],
    "MEDIUM": [
        "low pressure", "slow drain", "flickering", "noisy", "unstable",
        "intermittent", "sometimes", "occasional", "leaking", "dripping",
        "minor crack", "loose", "running", "keeps",
    ],
    "LOW": [
        "faded", "cosmetic", "paint", "slight", "small", "minor",
        "aesthetic", "worn", "scratched", "stain", "discolored",
    ],
}


def _rule_based_label(description):
    """
    Assign a training label based on urgency keywords in description.
    Used to ensure clean, consistent labels from synthetic data.
    """
    text = description.lower()
    for priority in ("URGENT", "HIGH", "MEDIUM", "LOW"):
        if any(kw in text for kw in URGENCY_KEYWORDS[priority]):
            return priority
    return None


class Command(BaseCommand):
    help = "Train TF-IDF + Logistic Regression NLP model for maintenance priority prediction"

    def handle(self, *args, **options):
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.linear_model import LogisticRegression
        from sklearn.model_selection import train_test_split, cross_val_score
        from sklearn.metrics import classification_report, accuracy_score
        from sklearn.pipeline import Pipeline
        import numpy as np
        import joblib

        from maintenance.models import MaintenanceRequest

        self.stdout.write("Loading maintenance requests from database...")
        records = MaintenanceRequest.objects.values("description", "priority")
        texts, labels = [], []

        rule_overrides = 0
        for r in records:
            desc = r["description"].strip()
            if not desc:
                continue
            rule_label = _rule_based_label(desc)
            if rule_label:
                labels.append(rule_label)
                rule_overrides += 1
            else:
                labels.append(r["priority"])
            texts.append(desc)

        self.stdout.write(f"  Total samples: {len(texts)}")
        self.stdout.write(f"  Rule-based re-labels applied: {rule_overrides}")

        from collections import Counter
        dist = Counter(labels)
        for cls, count in sorted(dist.items()):
            self.stdout.write(f"    {cls}: {count}")

        if len(texts) < 40:
            self.stderr.write("Not enough data to train. Need at least 40 samples.")
            return

        X_train, X_test, y_train, y_test = train_test_split(
            texts, labels, test_size=0.2, random_state=42, stratify=labels
        )
        self.stdout.write(f"\nTrain: {len(X_train)}  Test: {len(X_test)}")

        vectorizer = TfidfVectorizer(
            ngram_range=(1, 2),
            max_features=3000,
            sublinear_tf=True,
            min_df=1,
        )
        classifier = LogisticRegression(
            max_iter=1000,
            class_weight="balanced",
            random_state=42,
            C=1.0,
        )

        self.stdout.write("\nFitting TF-IDF vectorizer...")
        X_train_vec = vectorizer.fit_transform(X_train)
        X_test_vec = vectorizer.transform(X_test)

        self.stdout.write("Training Logistic Regression classifier...")
        classifier.fit(X_train_vec, y_train)

        y_pred = classifier.predict(X_test_vec)
        accuracy = accuracy_score(y_test, y_pred)
        report = classification_report(y_test, y_pred, output_dict=True)
        report_str = classification_report(y_test, y_pred)

        self.stdout.write(f"\n{'='*50}")
        self.stdout.write(f"Test Accuracy: {accuracy*100:.1f}%")
        self.stdout.write(f"\nClassification Report:\n{report_str}")

        classes = list(classifier.classes_)
        output_dir = os.path.join(os.path.dirname(__file__), "..", "..", "..", "exports", "ml")
        output_dir = os.path.normpath(output_dir)
        os.makedirs(output_dir, exist_ok=True)

        model_path = os.path.join(output_dir, "maintenance_nlp.joblib")
        joblib.dump({"vectorizer": vectorizer, "classifier": classifier, "classes": classes}, model_path)
        self.stdout.write(f"\nModel saved to: {model_path}")

        metrics = {
            "accuracy": round(accuracy, 4),
            "accuracy_pct": round(accuracy * 100, 1),
            "total_samples": len(texts),
            "train_samples": len(X_train),
            "test_samples": len(X_test),
            "classes": classes,
            "per_class": {
                cls: {
                    "precision": round(report[cls]["precision"], 4),
                    "recall": round(report[cls]["recall"], 4),
                    "f1": round(report[cls]["f1-score"], 4),
                    "support": int(report[cls]["support"]),
                }
                for cls in classes if cls in report
            },
            "macro_f1": round(report["macro avg"]["f1-score"], 4),
            "weighted_f1": round(report["weighted avg"]["f1-score"], 4),
        }

        metrics_path = os.path.join(output_dir, "maintenance_nlp_metrics.json")
        with open(metrics_path, "w") as f:
            json.dump(metrics, f, indent=2)
        self.stdout.write(f"Metrics saved to: {metrics_path}")
        self.stdout.write(self.style.SUCCESS("\nTraining complete!"))
