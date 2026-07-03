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


class Command(BaseCommand):
    help = "Train TF-IDF + Logistic Regression NLP model for maintenance priority prediction"

    def handle(self, *args, **options):
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.linear_model import LogisticRegression
        from sklearn.model_selection import train_test_split, cross_val_score
        from sklearn.metrics import classification_report, accuracy_score
        from sklearn.pipeline import FeatureUnion, Pipeline
        import numpy as np
        import joblib

        from maintenance.models import MaintenanceRequest

        self.stdout.write("Loading maintenance requests from database...")
        records = MaintenanceRequest.objects.values("description", "priority")
        texts, labels = [], []

        for r in records:
            desc = (r["description"] or "").strip()
            priority = (r["priority"] or "").strip()
            if not desc or not priority:
                continue
            texts.append(desc)
            labels.append(priority)

        self.stdout.write(f"  Total samples: {len(texts)}")

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

        features = FeatureUnion([
            ("word_tfidf", TfidfVectorizer(
                ngram_range=(1, 3),
                max_features=3000,
                sublinear_tf=True,
                min_df=1,
                max_df=0.9,
                stop_words=None,
            )),
            ("char_tfidf", TfidfVectorizer(
                analyzer="char_wb",
                ngram_range=(3, 5),
                max_features=2000,
                sublinear_tf=True,
                min_df=1,
                max_df=0.9,
            )),
        ])

        candidates = {
            "LogisticRegression": LogisticRegression(
                max_iter=2000,
                class_weight="balanced",
                random_state=42,
                C=1.0,
                solver="lbfgs",
            ),
            "RandomForest": RandomForestClassifier(
                n_estimators=150,
                class_weight="balanced",
                random_state=42,
                n_jobs=-1,
            ),
        }

        best_model = None
        best_accuracy = -1.0
        best_report = None
        best_name = None
        best_classes = None

        for name, classifier in candidates.items():
            pipeline = Pipeline([
                ("features", features),
                ("classifier", classifier),
            ])

            self.stdout.write(f"\nRunning cross-validation for {name}...")
            cv_scores = cross_val_score(pipeline, X_train, y_train, cv=4, scoring="accuracy", n_jobs=-1)
            self.stdout.write(f"  CV accuracy ({name}): {cv_scores.mean()*100:.1f}% (+/- {cv_scores.std()*100:.1f}%)")

            self.stdout.write(f"Training {name} pipeline on the full training set...")
            pipeline.fit(X_train, y_train)

            y_pred = pipeline.predict(X_test)
            accuracy = accuracy_score(y_test, y_pred)
            report = classification_report(y_test, y_pred, output_dict=True)
            report_str = classification_report(y_test, y_pred)

            self.stdout.write(f"\n{'='*50}")
            self.stdout.write(f"{name} Test Accuracy: {accuracy*100:.1f}%")
            self.stdout.write(f"\n{name} Classification Report:\n{report_str}")

            if accuracy > best_accuracy:
                best_accuracy = accuracy
                best_model = pipeline
                best_report = report
                best_name = name
                best_classes = list(pipeline.named_steps["classifier"].classes_)

        if best_model is None:
            self.stderr.write("Failed to train any model.")
            return

        self.stdout.write(f"\nBest model selected: {best_name} with accuracy {best_accuracy*100:.1f}%")

        classes = best_classes
        output_dir = os.path.join(os.path.dirname(__file__), "..", "..", "..", "exports", "ml")
        output_dir = os.path.normpath(output_dir)
        os.makedirs(output_dir, exist_ok=True)

        model_path = os.path.join(output_dir, "maintenance_nlp.joblib")
        joblib.dump({"pipeline": best_model, "classes": classes, "model_name": best_name}, model_path)
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
