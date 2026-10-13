# PayMongo Webhook Idempotency Test Script
# Run this after completing a PayMongo payment

$checkoutSessionId = Read-Host "Enter the checkout_session_id from your payment"

# Build webhook payload
$payload = @{
    data = @{
        attributes = @{
            type = "checkout_session.payment.paid"
            data = @{
                id = $checkoutSessionId
                attributes = @{
                    metadata = @{}
                    payments = @(
                        @{
                            id = "pay_test_duplicate"
                            attributes = @{
                                source = @{ type = "card" }
                            }
                        }
                    )
                }
            }
        }
    }
} | ConvertTo-Json -Depth 10

Write-Host ""
Write-Host "=== Sending First Webhook (Should process if not already approved) ===" -ForegroundColor Yellow

$response1 = Invoke-WebRequest -Uri "http://127.0.0.1:8000/payments/paymongo/webhook/" `
    -Method POST `
    -Headers @{
        "Content-Type" = "application/json"
        "Paymongo-Signature" = "t=$([int][double]::Parse((Get-Date -UFormat %s))),v1=fake_for_testing"
    } `
    -Body $payload

Write-Host "First Response Status: $($response1.StatusCode)"
Write-Host "First Response Body: $($response1.Content)"

Write-Host ""
Write-Host "=== Sending Second Webhook (Duplicate - Should be idempotent) ===" -ForegroundColor Yellow

$response2 = Invoke-WebRequest -Uri "http://127.0.0.1:8000/payments/paymongo/webhook/" `
    -Method POST `
    -Headers @{
        "Content-Type" = "application/json"
        "Paymongo-Signature" = "t=$([int][double]::Parse((Get-Date -UFormat %s))),v1=fake_for_testing"
    } `
    -Body $payload

Write-Host "Second Response Status: $($response2.StatusCode)"
Write-Host "Second Response Body: $($response2.Content)"

Write-Host ""
Write-Host "=== Checking Payment Status ===" -ForegroundColor Green

python manage.py shell -c "
from payments.models import ManualPayment
payment = ManualPayment.objects.filter(checkout_session_id='$checkoutSessionId').first()
if payment:
    print(f\"Payment ID: {payment.id}\")
    print(f\"Status: {payment.status}\")
    print(f\"Amount: ₱{payment.amount:,.2f}\")
    print(f\"Bills Paid: {payment.bill_ids}\")
else:
    print(\"Payment not found\")
"

Write-Host ""
Write-Host "=== Test Complete ===" -ForegroundColor Cyan
Write-Host "Check: Both webhooks returned 200, but payment was only processed once"
