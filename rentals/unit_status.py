from rentals.models import Lease


def expected_unit_status(unit) -> str:
    if unit.status == "MAINTENANCE":
        return "MAINTENANCE"
    has_active_lease = Lease.objects.filter(
        unit=unit,
        status=Lease.STATUS_ACTIVE,
        is_active=True,
    ).exists()
    return "OCCUPIED" if has_active_lease else "AVAILABLE"


def sync_unit_status(unit, *, save=True) -> bool:
    expected_status = expected_unit_status(unit)
    if unit.status == expected_status:
        return False
    unit.status = expected_status
    if expected_status == "MAINTENANCE":
        unit.is_active = False
    elif not unit.is_active:
        unit.is_active = True
    if save:
        unit.save(update_fields=["status", "is_active"])
    return True
