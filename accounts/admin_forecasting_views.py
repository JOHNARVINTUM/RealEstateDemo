from datetime import datetime
import logging

from django.db.models import Sum, F, ExpressionWrapper, DecimalField
from django.shortcuts import render
from django.utils import timezone

from billing.models import MonthlyBill
from maintenance.models import MaintenanceRequest
from rentals.models import Notification
from water.models import WaterReading

from .admin_portal_views import admin_required


logger = logging.getLogger(__name__)


@admin_required
def admin_forecasting(request):
    today = timezone.now().date()

    selected_year = request.GET.get("year", "")
    try:
        selected_year = int(selected_year)
    except (ValueError, TypeError):
        selected_year = today.year

    min_year = today.year - 5
    max_year = today.year
    selected_year = max(min_year, min(max_year, selected_year))
    year_choices = list(range(min_year, max_year + 1))

    if selected_year < today.year:
        current_month_start = datetime(selected_year, 12, 1).date()
    else:
        current_month_start = today.replace(day=1)

    def _month_date(i):
        y, m = current_month_start.year, current_month_start.month - i
        while m <= 0:
            m += 12
            y -= 1
        return datetime(y, m, 1).date()

    def _moving_avg_forecast(series, window=3, steps=3):
        if len(series) < window:
            return [round(sum(series) / max(len(series), 1), 2)] * steps
        tail = series[-window:]
        forecasts = []
        buf = list(tail)
        for _ in range(steps):
            val = round(sum(buf[-window:]) / window, 2)
            forecasts.append(val)
            buf.append(val)
        return forecasts

    def _accuracy_metrics(series, window=3, test_steps=3):
        import math

        n = len(series)
        if n < window + test_steps:
            return {"rmse": None, "mae": None, "mape": None}
        train = series[: n - test_steps]
        actual = series[n - test_steps :]
        preds = []
        buf = list(train)
        for _ in range(test_steps):
            val = sum(buf[-window:]) / window
            preds.append(val)
            buf.append(val)
        errors = [a - p for a, p in zip(actual, preds)]
        mae = round(sum(abs(e) for e in errors) / test_steps, 2)
        rmse = round(math.sqrt(sum(e**2 for e in errors) / test_steps), 2)
        non_zero = [(a, e) for a, e in zip(actual, errors) if a != 0]
        mape = (
            round(sum(abs(e / a) for a, e in non_zero) / len(non_zero) * 100, 2)
            if non_zero
            else None
        )
        return {"rmse": rmse, "mae": mae, "mape": mape}

    def _clean_series(series):
        s = list(series)
        while s and s[-1] == 0:
            s.pop()
        return s

    def _sarima_forecast(series, order=(0, 1, 1), seasonal_order=(1, 1, 1, 12), steps=6):
        try:
            import warnings
            import numpy as np
            from statsmodels.tsa.statespace.sarimax import SARIMAX

            s = _clean_series(series)
            if len(s) < 18:
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
            mean = [round(float(v), 2) for v in forecast_obj.predicted_mean]
            ci = np.array(forecast_obj.conf_int(alpha=0.2))
            lower = [round(float(v), 2) for v in ci[:, 0]]
            upper = [round(float(v), 2) for v in ci[:, 1]]
            return mean, lower, upper
        except ImportError:
            return None, None, None
        except Exception as exc:
            logger.error("SARIMA forecast error: %s", exc)
            return None, None, None

    def _sarima_metrics(series, order=(0, 1, 1), seasonal_order=(1, 1, 1, 12), test_steps=6):
        try:
            import math
            import warnings
            from statsmodels.tsa.statespace.sarimax import SARIMAX

            s = _clean_series(series)
            n = len(s)
            if n < 18:
                return {"rmse": None, "mae": None, "mape": None}
            train = s[: n - test_steps]
            actual = s[n - test_steps :]
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
            preds = [float(v) for v in fit.get_forecast(steps=test_steps).predicted_mean]
            errors = [a - p for a, p in zip(actual, preds)]
            mae = round(sum(abs(e) for e in errors) / test_steps, 2)
            rmse = round(math.sqrt(sum(e**2 for e in errors) / test_steps), 2)
            non_zero = [(a, e) for a, e in zip(actual, errors) if a != 0]
            mape = (
                round(sum(abs(e / a) for a, e in non_zero) / len(non_zero) * 100, 2)
                if non_zero
                else None
            )
            return {"rmse": rmse, "mae": mae, "mape": mape}
        except ImportError:
            return {"rmse": None, "mae": None, "mape": None}
        except Exception as exc:
            logger.error("SARIMA metrics error: %s", exc)
            return {"rmse": None, "mae": None, "mape": None}

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

    revenue_series, water_series, maintenance_series, hist_labels = [], [], [], []

    for i in range(24, -1, -1):
        md = _month_date(i)
        rev = float(
            MonthlyBill.objects.filter(
                billing_month__year=md.year,
                billing_month__month=md.month,
            ).aggregate(
                total=Sum(
                    ExpressionWrapper(
                        F("base_rent") + F("water_amount") + F("interest"),
                        output_field=DecimalField(),
                    )
                )
            )["total"]
            or 0
        )
        water = float(
            WaterReading.objects.filter(
                reading_month__year=md.year,
                reading_month__month=md.month,
            ).aggregate(total=Sum("consumption"))["total"]
            or 0
        )
        maint = MaintenanceRequest.objects.filter(
            created_at__year=md.year,
            created_at__month=md.month,
        ).count()

        revenue_series.append(rev)
        water_series.append(water)
        maintenance_series.append(maint)
        hist_labels.append(md.strftime("%b %Y"))

    forecast_labels = _next_month_labels(3)
    revenue_forecast = _moving_avg_forecast(revenue_series, window=3, steps=3)
    water_forecast = _moving_avg_forecast(water_series, window=3, steps=3)
    maintenance_forecast = _moving_avg_forecast(maintenance_series, window=3, steps=3)

    revenue_metrics = _accuracy_metrics(revenue_series)
    water_metrics = _accuracy_metrics(water_series)
    maintenance_metrics = _accuracy_metrics(maintenance_series)

    rev_sarima_fc, rev_sarima_lower, rev_sarima_upper = _sarima_forecast(
        revenue_series, order=(0, 1, 1), seasonal_order=(1, 1, 1, 12), steps=3
    )

    revenue_sarima_metrics = _sarima_metrics(
        revenue_series, order=(0, 1, 1), seasonal_order=(1, 1, 1, 12)
    )

    hist_revenue_last12 = revenue_series[-36:]
    hist_water_last12 = water_series[-36:]
    hist_maintenance_last12 = maintenance_series[-36:]
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

    rev_next = rev_sarima_fc[0] if rev_sarima_fc else revenue_forecast[0]
    rev_trend = _trend_direction(revenue_series)
    if rev_trend == "up":
        revenue_insight = (
            f"Revenue is trending upward. Next month's forecast is ₱{rev_next:,.0f}, "
            "which is higher than recent months. Collection efforts are paying off."
        )
    elif rev_trend == "down":
        revenue_insight = (
            f"Revenue has been declining. Next month's estimate is ₱{rev_next:,.0f}. "
            "Consider following up on overdue payments."
        )
    else:
        revenue_insight = (
            f"Revenue is holding steady. Expect approximately ₱{rev_next:,.0f} "
            "next month based on historical patterns."
        )

    water_next = water_forecast[0]
    water_trend = _trend_direction(water_series)
    if water_trend == "up":
        water_insight = (
            f"Water consumption is rising. Next month's estimate is {water_next:,.1f} m³. "
            "This may indicate more tenants or seasonal usage increase."
        )
    elif water_trend == "down":
        water_insight = (
            f"Water usage is decreasing. Next month's forecast is {water_next:,.1f} m³, "
            "likely due to fewer occupants or conservation."
        )
    else:
        water_insight = (
            f"Water usage is stable. Expect about {water_next:,.1f} m³ next month "
            "consistent with recent months."
        )

    maint_next = maintenance_forecast[0]
    maint_trend = _trend_direction(maintenance_series)
    if maint_trend == "up":
        maintenance_insight = (
            f"Maintenance requests are increasing. Expect around {maint_next:.0f} requests "
            "next month. Consider scheduling preventive maintenance."
        )
    elif maint_trend == "down":
        maintenance_insight = (
            f"Maintenance requests are declining. Forecast: about {maint_next:.0f} requests next month."
        )
    else:
        maintenance_insight = (
            f"Maintenance volume is steady at around {maint_next:.0f} requests expected next month."
        )

    return render(
        request,
        "admin_portal/forecasting.html",
        {
            "hist_labels": hist_labels_last12,
            "hist_revenue": hist_revenue_last12,
            "hist_water": hist_water_last12,
            "hist_maintenance": hist_maintenance_last12,
            "forecast_labels": forecast_labels,
            "revenue_forecast": revenue_forecast,
            "water_forecast": water_forecast,
            "maintenance_forecast": maintenance_forecast,
            "revenue_metrics": revenue_metrics,
            "water_metrics": water_metrics,
            "maintenance_metrics": maintenance_metrics,
            "rev_sarima_fc": rev_sarima_fc,
            "rev_sarima_lower": rev_sarima_lower,
            "rev_sarima_upper": rev_sarima_upper,
            "revenue_sarima_metrics": revenue_sarima_metrics,
            "sarima_available": rev_sarima_fc is not None,
            "selected_year": selected_year,
            "year_choices": year_choices,
            "revenue_insight": revenue_insight,
            "water_insight": water_insight,
            "maintenance_insight": maintenance_insight,
            "unread_count": Notification.objects.filter(is_read=False).count(),
        },
    )


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
