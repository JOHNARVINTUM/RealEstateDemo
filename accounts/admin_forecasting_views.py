from datetime import datetime, timedelta
import logging

from django.db.models import Sum, Q
from django.db.models.functions import TruncMonth
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone

from billing.models import MonthlyBill
from rentals.models import Notification

from .admin_portal_views import admin_required


logger = logging.getLogger(__name__)


@admin_required
def admin_forecasting(request):
    today = timezone.now().date()
    selected_year, year_choices = _forecasting_year_options(request, today)

    return render(
        request,
        "admin_portal/forecasting.html",
        {
            "selected_year": selected_year,
            "year_choices": year_choices,
            "unread_count": Notification.objects.filter(is_read=False).count(),
        },
    )


@admin_required
def admin_forecasting_data(request):
    context = _build_forecasting_context(request)
    payload = {
        "hist_labels": context["hist_labels"],
        "hist_revenue": context["hist_revenue"],
        "forecast_labels": context["forecast_labels"],
        "revenue_forecast": context["revenue_forecast"],
        "rev_naive_fc": context["rev_naive_fc"],
        "rev_arima_fc": context["rev_arima_fc"],
        "rev_sarima_fc": context["rev_sarima_fc"],
        "rev_selected_lower": context["rev_selected_lower"],
        "rev_selected_upper": context["rev_selected_upper"],
        "rev_sarima_lower": context["rev_sarima_lower"],
        "rev_sarima_upper": context["rev_sarima_upper"],
        "revenue_naive_metrics": context["revenue_naive_metrics"],
        "revenue_arima_metrics": context["revenue_arima_metrics"],
        "revenue_sarima_metrics": context["revenue_sarima_metrics"],
        "selected_model": context["selected_model"],
        "sarima_available": context["sarima_available"],
        "selected_year": context["selected_year"],
        "year_choices": context["year_choices"],
        "revenue_insight": context["revenue_insight"],
        "sarima_backtest_rows": context["sarima_backtest_rows"],
        "history_month_count": context["history_month_count"],
        "history_range_label": context["history_range_label"],
        "forecast_horizon": context["forecast_horizon"],
        "selected_model_order": context["selected_model_order"],
        "selected_model_seasonal_order": context["selected_model_seasonal_order"],
        "sarima_order": context["sarima_order"],
        "sarima_seasonal_order": context["sarima_seasonal_order"],
        "arima_order": context["arima_order"],
    }
    return JsonResponse(payload)


def _forecasting_year_options(request, today):
    selected_year = request.GET.get("year", "")
    try:
        selected_year = int(selected_year)
    except (ValueError, TypeError):
        selected_year = today.year

    min_year = today.year - 5
    max_year = today.year
    selected_year = max(min_year, min(max_year, selected_year))
    year_choices = list(range(min_year, max_year + 1))
    return selected_year, year_choices


def _build_forecasting_context(request):
    today = timezone.now().date()

    selected_year, year_choices = _forecasting_year_options(request, today)
    forecast_horizon = 3
    history_months = 36
    current_month_first = today.replace(day=1)
    last_complete_month_start = (current_month_first - timedelta(days=1)).replace(day=1)

    if selected_year < today.year:
        current_month_start = datetime(selected_year, 12, 1).date()
    else:
        current_month_start = last_complete_month_start

    def _month_date(i):
        y, m = current_month_start.year, current_month_start.month - i
        while m <= 0:
            m += 12
            y -= 1
        return datetime(y, m, 1).date()

    def _clean_series(series):
        s = list(series)
        while s and s[-1] == 0:
            s.pop()
        return s

    def _sanitize_forecast_point(value):
        import math

        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(numeric) or numeric < 0:
            return None
        return round(numeric, 2)

    def _sanitize_forecast_series(values):
        if values is None:
            return None
        sanitized = [_sanitize_forecast_point(value) for value in values]
        return sanitized if any(value is not None for value in sanitized) else None

    def _metric_dict(actual, preds):
        import math

        if not actual or not preds or len(actual) != len(preds):
            return {"rmse": None, "mae": None, "mape": None}
        errors = [a - p for a, p in zip(actual, preds)]
        count = len(errors)
        mae = round(sum(abs(e) for e in errors) / count, 2)
        rmse = round(math.sqrt(sum(e**2 for e in errors) / count), 2)
        non_zero = [(a, e) for a, e in zip(actual, errors) if a != 0]
        mape = (
            round(sum(abs(e / a) for a, e in non_zero) / len(non_zero) * 100, 2)
            if non_zero
            else None
        )
        return {"rmse": rmse, "mae": mae, "mape": mape}

    def _minimum_history_required(seasonal_period=None):
        if seasonal_period and seasonal_period > 1:
            return max(18, seasonal_period * 2)
        return 12

    def _naive_forecast(series, steps=6, seasonal_period=None):
        s = _clean_series(series)
        if not s:
            return None
        if seasonal_period and len(s) >= seasonal_period:
            base = s[-seasonal_period:]
            return [round(float(base[i % len(base)]), 2) for i in range(steps)]
        return [round(float(s[-1]), 2) for _ in range(steps)]

    def _naive_metrics(series, test_steps=6, seasonal_period=None):
        s = _clean_series(series)
        n = len(s)
        minimum_history = max(_minimum_history_required(seasonal_period), test_steps + 1)
        if n < minimum_history:
            return {"rmse": None, "mae": None, "mape": None}
        preds, actual = [], []
        start_index = max(n - test_steps, minimum_history)
        for idx in range(start_index, n):
            pred = _naive_forecast(s[:idx], steps=1, seasonal_period=seasonal_period)
            if not pred:
                continue
            preds.append(float(pred[0]))
            actual.append(float(s[idx]))
        return _metric_dict(actual, preds)

    def _sarimax_forecast(series, order=(0, 1, 1), seasonal_order=(0, 0, 0, 0), steps=6):
        try:
            import warnings
            import numpy as np
            from statsmodels.tsa.statespace.sarimax import SARIMAX

            s = _clean_series(series)
            seasonal_period = seasonal_order[3] if seasonal_order and len(seasonal_order) > 3 else None
            if len(s) < _minimum_history_required(seasonal_period):
                return None, None, None
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                model = SARIMAX(
                    s,
                    order=order,
                    seasonal_order=seasonal_order,
                    enforce_stationarity=False,
                    enforce_invertibility=False,
                )
                fit = model.fit(disp=False)
            forecast_obj = fit.get_forecast(steps=steps)
            mean = _sanitize_forecast_series(forecast_obj.predicted_mean)
            ci = np.array(forecast_obj.conf_int(alpha=0.2))
            lower = _sanitize_forecast_series(ci[:, 0])
            upper = _sanitize_forecast_series(ci[:, 1])
            return mean, lower, upper
        except ImportError:
            return None, None, None
        except Exception as exc:
            logger.error("SARIMA forecast error: %s", exc)
            return None, None, None

    def _sarimax_metrics(series, order=(0, 1, 1), seasonal_order=(0, 0, 0, 0), test_steps=6):
        try:
            import warnings
            from statsmodels.tsa.statespace.sarimax import SARIMAX

            s = _clean_series(series)
            n = len(s)
            seasonal_period = seasonal_order[3] if seasonal_order and len(seasonal_order) > 3 else None
            minimum_history = max(_minimum_history_required(seasonal_period), test_steps + 1)
            if n < minimum_history:
                return {"rmse": None, "mae": None, "mape": None}
            preds, actual = [], []
            start_index = max(n - test_steps, minimum_history)
            for idx in range(start_index, n):
                train = s[:idx]
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    model = SARIMAX(
                        train,
                        order=order,
                        seasonal_order=seasonal_order,
                        enforce_stationarity=False,
                        enforce_invertibility=False,
                    )
                    fit = model.fit(disp=False)
                preds.append(float(fit.get_forecast(steps=1).predicted_mean[0]))
                actual.append(float(s[idx]))
            return _metric_dict(actual, preds)
        except ImportError:
            return {"rmse": None, "mae": None, "mape": None}
        except Exception as exc:
            logger.error("SARIMA metrics error: %s", exc)
            return {"rmse": None, "mae": None, "mape": None}

    def _sarimax_backtest_rows(series, month_dates, order=(0, 1, 1), seasonal_order=(0, 0, 0, 0), test_steps=6):
        try:
            import warnings
            from statsmodels.tsa.statespace.sarimax import SARIMAX

            s = _clean_series(series)
            n = len(s)
            seasonal_period = seasonal_order[3] if seasonal_order and len(seasonal_order) > 3 else None
            minimum_history = max(_minimum_history_required(seasonal_period), test_steps + 1)
            if n < minimum_history:
                return []

            rows = []
            start_index = max(n - test_steps, minimum_history)
            for idx in range(start_index, n):
                train = s[:idx]
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    model = SARIMAX(
                        train,
                        order=order,
                        seasonal_order=seasonal_order,
                        enforce_stationarity=False,
                        enforce_invertibility=False,
                    )
                    fit = model.fit(disp=False)
                month_date = month_dates[idx]
                actual_value = round(float(s[idx]), 2)
                forecast_value = _sanitize_forecast_point(fit.get_forecast(steps=1).predicted_mean[0])
                if forecast_value is None:
                    continue
                rows.append({
                    "month_key": month_date.strftime("%Y-%m"),
                    "month_label": month_date.strftime("%B %Y"),
                    "actual": actual_value,
                    "sarima": forecast_value,
                    "difference": round(actual_value - forecast_value, 2),
                })
            return rows
        except ImportError:
            return []
        except Exception as exc:
            logger.error("SARIMA backtest rows error: %s", exc)
            return []

    def _best_sarimax_config(series, candidates, test_steps=6):
        ranked = []
        for candidate in candidates:
            metrics = _sarimax_metrics(
                series,
                order=candidate["order"],
                seasonal_order=candidate["seasonal_order"],
                test_steps=test_steps,
            )
            if metrics["rmse"] is None and metrics["mae"] is None and metrics["mape"] is None:
                continue
            ranked.append({
                "label": candidate["label"],
                "order": candidate["order"],
                "seasonal_order": candidate["seasonal_order"],
                "metrics": metrics,
                "rank": (
                    float("inf") if metrics["mape"] is None else metrics["mape"],
                    float("inf") if metrics["rmse"] is None else metrics["rmse"],
                    float("inf") if metrics["mae"] is None else metrics["mae"],
                ),
            })
        if not ranked:
            return None
        ranked.sort(key=lambda item: item["rank"])
        return ranked[0]

    def _next_month_labels(steps=3):
        labels = []
        y, m = current_month_start.year, current_month_start.month
        for _ in range(steps):
            m += 1
            if m > 12:
                m = 1
                y += 1
            labels.append(datetime(y, m, 1).strftime("%b %Y"))
        return labels

    revenue_series, hist_labels, hist_dates = [], [], []
    history_start = _month_date(history_months)
    history_end = (current_month_start + timedelta(days=32)).replace(day=1)
    monthly_collected_totals = {
        (row["month_bucket"].year, row["month_bucket"].month): float(
            (row["rent"] or 0)
            + (row["water"] or 0)
            + (row["parking"] or 0)
            + (row["interest"] or 0)
        )
        for row in MonthlyBill.objects.filter(
            billing_month__gte=history_start,
            billing_month__lt=history_end,
        )
        .annotate(month_bucket=TruncMonth("billing_month"))
        .values("month_bucket")
        .annotate(
            rent=Sum("rent_paid"),
            water=Sum("water_paid"),
            parking=Sum("parking_paid"),
            interest=Sum("interest", filter=Q(status="PAID")),
        )
    }

    for i in range(history_months, -1, -1):
        md = _month_date(i)
        rev = monthly_collected_totals.get((md.year, md.month), 0)
        revenue_series.append(rev)
        hist_labels.append(md.strftime("%b %Y"))
        hist_dates.append(md)

    forecast_labels = _next_month_labels(forecast_horizon)

    arima_candidates = [
        {"label": "ARIMA", "order": (0, 1, 1), "seasonal_order": (0, 0, 0, 0)},
        {"label": "ARIMA", "order": (1, 1, 1), "seasonal_order": (0, 0, 0, 0)},
        {"label": "ARIMA", "order": (1, 1, 0), "seasonal_order": (0, 0, 0, 0)},
    ]
    sarima_candidates = [
        {"label": "SARIMA", "order": (0, 1, 1), "seasonal_order": (1, 1, 1, 12)},
        {"label": "SARIMA", "order": (1, 1, 1), "seasonal_order": (1, 1, 1, 12)},
        {"label": "SARIMA", "order": (1, 1, 0), "seasonal_order": (1, 1, 0, 12)},
    ]

    best_arima = _best_sarimax_config(revenue_series, arima_candidates, test_steps=forecast_horizon)
    best_sarima = _best_sarimax_config(revenue_series, sarima_candidates, test_steps=forecast_horizon)

    rev_naive_fc = _naive_forecast(revenue_series, steps=forecast_horizon, seasonal_period=12)
    revenue_naive_metrics = _naive_metrics(revenue_series, test_steps=forecast_horizon, seasonal_period=12)

    if best_arima:
        rev_arima_fc, _, _ = _sarimax_forecast(
            revenue_series,
            order=best_arima["order"],
            seasonal_order=best_arima["seasonal_order"],
            steps=forecast_horizon,
        )
        revenue_arima_metrics = dict(best_arima["metrics"])
    else:
        rev_arima_fc = None
        revenue_arima_metrics = {"rmse": None, "mae": None, "mape": None}

    if best_sarima:
        rev_sarima_fc, rev_sarima_lower, rev_sarima_upper = _sarimax_forecast(
            revenue_series,
            order=best_sarima["order"],
            seasonal_order=best_sarima["seasonal_order"],
            steps=forecast_horizon,
        )
        sarima_backtest_rows = _sarimax_backtest_rows(
            revenue_series,
            hist_dates,
            order=best_sarima["order"],
            seasonal_order=best_sarima["seasonal_order"],
            test_steps=forecast_horizon,
        )
    else:
        rev_sarima_fc, rev_sarima_lower, rev_sarima_upper = None, None, None
        sarima_backtest_rows = []

    if sarima_backtest_rows:
        revenue_sarima_metrics = _metric_dict(
            [row["actual"] for row in sarima_backtest_rows],
            [row["sarima"] for row in sarima_backtest_rows],
        )
    else:
        revenue_sarima_metrics = {"rmse": None, "mae": None, "mape": None}

    selected_model = "SARIMA"
    history_month_count = len(revenue_series)
    history_range_label = f"{hist_labels[0]} to {hist_labels[-1]}" if hist_labels else "No history"
    arima_order = list(best_arima["order"]) if best_arima else None
    sarima_order = list(best_sarima["order"]) if best_sarima else None
    sarima_seasonal_order = list(best_sarima["seasonal_order"]) if best_sarima else None
    selected_model_order = sarima_order
    selected_model_seasonal_order = sarima_seasonal_order
    selected_forecast = rev_sarima_fc
    rev_selected_lower = rev_sarima_lower
    rev_selected_upper = rev_sarima_upper

    hist_revenue_last12 = revenue_series[-36:]
    hist_labels_last12 = hist_labels[-36:]

    def _trend_direction(series, window=3):
        if len(series) < window * 2:
            return "stable"
        recent_avg = sum(series[-window:]) / window
        prev_avg = sum(series[-window * 2 : -window]) / window
        if prev_avg == 0:
            return "stable"
        pct_change = ((recent_avg - prev_avg) / prev_avg) * 100
        if pct_change > 5:
            return "up"
        if pct_change < -5:
            return "down"
        return "stable"

    rev_trend = _trend_direction(revenue_series)
    first_selected_forecast = None
    if selected_forecast:
        first_selected_forecast = next((value for value in selected_forecast if value is not None), None)

    if first_selected_forecast is None:
        revenue_insight = (
            "SARIMA forecast is unavailable because there is not enough usable revenue history yet or the forecast output was invalid. Naive and ARIMA remain visible for comparison metrics only."
        )
    elif rev_trend == "up":
        rev_next = first_selected_forecast
        revenue_insight = (
            f"Revenue is trending upward. The SARIMA forecast estimates PHP {rev_next:,.0f} next month. "
            "Recent collections are outperforming the prior period."
        )
    elif rev_trend == "down":
        rev_next = first_selected_forecast
        revenue_insight = (
            f"Revenue has been declining. The SARIMA forecast estimates PHP {rev_next:,.0f} next month. "
            "Collections need closer follow-up."
        )
    else:
        rev_next = first_selected_forecast
        revenue_insight = (
            f"Revenue is stable. The SARIMA forecast expects about PHP {rev_next:,.0f} next month "
            "based on recent history and seasonality checks."
        )

    return {
        "hist_labels": hist_labels_last12,
        "hist_revenue": hist_revenue_last12,
        "forecast_labels": forecast_labels,
        "revenue_forecast": [],
        "rev_naive_fc": rev_naive_fc,
        "rev_arima_fc": rev_arima_fc,
        "rev_sarima_fc": rev_sarima_fc,
        "rev_selected_lower": rev_selected_lower,
        "rev_selected_upper": rev_selected_upper,
        "rev_sarima_lower": rev_sarima_lower,
        "rev_sarima_upper": rev_sarima_upper,
        "revenue_naive_metrics": revenue_naive_metrics,
        "revenue_arima_metrics": revenue_arima_metrics,
        "revenue_sarima_metrics": revenue_sarima_metrics,
        "selected_model": selected_model,
        "sarima_available": rev_sarima_fc is not None,
        "selected_year": selected_year,
        "year_choices": year_choices,
        "revenue_insight": revenue_insight,
        "sarima_backtest_rows": sarima_backtest_rows,
        "history_month_count": history_month_count,
        "history_range_label": history_range_label,
        "forecast_horizon": forecast_horizon,
        "selected_model_order": selected_model_order,
        "selected_model_seasonal_order": selected_model_seasonal_order,
        "sarima_order": sarima_order,
        "sarima_seasonal_order": sarima_seasonal_order,
        "arima_order": arima_order,
    }


@admin_required
def admin_billed_this_month(request):
    """Breakdown of all bills generated this month."""
    today = timezone.now().date()

    month_str = request.GET.get("month", "").strip()
    if month_str:
        try:
            target = datetime.strptime(month_str, "%Y-%m").date()
        except ValueError:
            target = today
    else:
        target = today

    all_bills = list(
        MonthlyBill.objects.filter(
            billing_month__year=target.year,
            billing_month__month=target.month,
        )
        .select_related("lease", "lease__unit", "lease__tenant", "lease__tenant__tenantprofile")
        .order_by("lease__unit__number")
    )

    bills_with_payment = [
        bill for bill in all_bills if bill.rent_paid > 0 or bill.water_paid > 0 or bill.parking_paid > 0
    ]
    for bill in bills_with_payment:
        bill.total_collected_amount = bill.rent_paid + bill.water_paid + bill.parking_paid

    fully_paid_count = sum(1 for bill in all_bills if bill.status == "PAID")
    unpaid_count = sum(1 for bill in all_bills if bill.status == "UNPAID")
    partial_count = sum(1 for bill in all_bills if bill.status == "PARTIALLY_PAID")

    total_rent = sum(bill.rent_paid for bill in all_bills)
    total_water = sum(bill.water_paid for bill in all_bills)
    total_parking = sum(bill.parking_paid for bill in all_bills)
    total_interest = sum(bill.interest for bill in all_bills if bill.status == "PAID")
    grand_total = total_rent + total_water + total_parking + total_interest

    return render(
        request,
        "admin_portal/billed_this_month.html",
        {
            "bills": bills_with_payment,
            "total_bills": len(all_bills),
            "fully_paid_count": fully_paid_count,
            "unpaid_count": unpaid_count,
            "partial_count": partial_count,
            "total_rent": total_rent,
            "total_water": total_water,
            "total_parking": total_parking,
            "total_interest": total_interest,
            "grand_total": grand_total,
            "target_month": target,
            "current_month_str": today.strftime("%Y-%m"),
            "unread_count": Notification.objects.filter(is_read=False).count(),
        },
    )

