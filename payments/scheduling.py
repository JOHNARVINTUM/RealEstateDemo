from datetime import datetime, time, timedelta


OFFICE_START_TIME = time(9, 0)
OFFICE_END_TIME = time(17, 0)
OFFICE_SLOT_MINUTES = 30
OFFICE_HOURS_LABEL = "Monday to Friday, 9:00 AM - 5:00 PM"


def f2f_time_slots():
    slots = []
    current = datetime.combine(datetime.today(), OFFICE_START_TIME)
    end = datetime.combine(datetime.today(), OFFICE_END_TIME)
    while current <= end:
        slots.append(current.time())
        current += timedelta(minutes=OFFICE_SLOT_MINUTES)
    return slots


def is_office_schedule(preferred_date, preferred_time):
    if preferred_date and preferred_date.weekday() >= 5:
        return False, "Please choose a weekday schedule. Office cash payments are available Monday to Friday only."
    if preferred_time and preferred_time not in f2f_time_slots():
        return False, f"Please choose a time within office hours: {OFFICE_HOURS_LABEL}."
    return True, ""
