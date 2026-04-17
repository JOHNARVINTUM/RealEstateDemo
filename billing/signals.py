from django.db.models.signals import post_delete
from django.dispatch import receiver

from billing.models import MonthlyBill
from billing.services import remove_bill_references_from_payment_history


@receiver(post_delete, sender=MonthlyBill)
def cleanup_payment_history_after_bill_delete(sender, instance, **kwargs):
    remove_bill_references_from_payment_history(instance.pk)
