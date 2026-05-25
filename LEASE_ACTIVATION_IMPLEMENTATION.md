# Lease Activation Workflow Implementation

## Summary

Implemented a real-world lease activation workflow where:
1. Admin creates lease → Status: PENDING_PAYMENT
2. Tenant pays via PayMongo/GCash/Cash
3. Lease activates → Status: ACTIVE
4. Billing generates and unit becomes occupied

## Changes Made

### Phase 1: Model Changes
**File: `rentals/models.py`**
- Added `status` field with choices: PENDING_PAYMENT, ACTIVE, TERMINATED, EXPIRED
- Added `activated_at` timestamp field
- Updated `save()` to NOT auto-activate (removed date-based auto-activation)
- Added `activate()` method for centralized activation
- Added `deactivate()` method for centralized deactivation
- Added helper properties: `is_pending_payment`, `display_status`

**Migration: `rentals/migrations/0025_add_lease_status.py`**
- Adds status and activated_at fields
- Alters is_active default to False

**Migration: `rentals/migrations/0026_set_existing_leases_active.py`**
- Sets existing leases with is_active=True to status='ACTIVE'
- Sets existing leases with is_active=False to status='TERMINATED'

### Phase 2: Centralized Activation Service
**File: `rentals/services.py`**
- Added `LeaseActivationService` class
- `activate_lease_after_payment()` method handles:
  - Lease activation (status → ACTIVE, is_active → True)
  - Unit occupancy update (status → OCCUPIED)
  - Billing generation (ensure_bills_since_move_in)
  - First bill marking as PAID
  - Payment record creation
  - Duplicate activation prevention
  - Transaction safety

### Phase 3: Admin Lease Creation Flow
**File: `accounts/admin_portal_views.py`**
- Modified `admin_create_lease`:
  - Removed immediate billing generation
  - Removed immediate unit occupancy
  - Removed move-in payment record creation
  - Lease created with status='PENDING_PAYMENT'
  - Redirects to payment page instead of tenant list
  - Sends pending lease email to tenant

**New View: `admin_lease_payment`**
- Shows lease summary
- Payment method selection: PayMongo, GCash, Cash
- Redirects to appropriate payment flow

**New Template: `templates/admin_portal/lease_payment.html`**
- Lease summary display
- Payment method cards
- Important notes about activation

**File: `accounts/admin_portal_urls.py`**
- Added URL pattern for `admin_lease_payment`

### Phase 4: Webhook Integration
**File: `payments/views.py`**
- Updated `admin_paymongo_checkout_generate`:
  - Includes `lease_id` in PayMongo metadata
  - Enables webhook to activate specific lease

- Updated `_auto_approve_paymongo_payment`:
  - Checks for lease_id in metadata
  - Calls `LeaseActivationService` for move-in payments
  - Handles duplicate activation (idempotent)

### Phase 5: Tenant Dashboard
**File: `rentals/views.py`**
- Updated `tenant_dashboard`:
  - Includes PENDING_PAYMENT leases in query
  - Only generates bills for ACTIVE leases
  - Shows pending lease status to tenant

### Phase 6: Payment Approval Integration
**File: `billing/services.py`**
- Updated `approve_manual_payment`:
  - Checks for pending lease on move-in payments
  - Calls `LeaseActivationService` for activation
  - Fallback to normal approval if activation fails

### Phase 7: Admin Reports
**File: `accounts/admin_portal_views.py`**
- Updated `admin_dashboard`:
  - Uses `status='ACTIVE'` instead of `is_active=True`
  - Updated all lease count queries
  - Updated expected rent calculations

- Updated `deactivate_tenant`:
  - Uses `status='ACTIVE'` instead of `is_active=True`
  - Uses `lease.deactivate()` method

- Updated `admin_tenants`:
  - Uses `status='ACTIVE'` for active tenant count

## New Flow

### Before (Old Flow)
1. Admin fills lease form
2. Click "Save Lease"
3. Lease created with is_active=True
4. Unit marked OCCUPIED
5. Bills generated immediately
6. Move-in payment recorded
7. First bill marked PAID

### After (New Flow)
1. Admin fills lease form
2. Click "Save Lease"
3. Lease created with status='PENDING_PAYMENT', is_active=False
4. Unit remains AVAILABLE
5. No bills generated yet
6. Redirect to payment page
7. Admin selects payment method (PayMongo/GCash/Cash)
8. Tenant pays
9. Webhook/approval calls `LeaseActivationService`
10. Lease activates (status='ACTIVE', is_active=True)
11. Unit marked OCCUPIED
12. Bills generated
13. First bill marked PAID
14. Tenant receives portal access

## Affected Files

### Models
- `rentals/models.py` - Status field, activation methods

### Services
- `rentals/services.py` - LeaseActivationService
- `billing/services.py` - Payment approval integration

### Views
- `accounts/admin_portal_views.py` - Lease creation, payment page, dashboard
- `rentals/views.py` - Tenant dashboard
- `payments/views.py` - Webhook, admin checkout

### Templates
- `templates/admin_portal/lease_payment.html` - New payment page

### URLs
- `accounts/admin_portal_urls.py` - New payment page route

### Migrations
- `rentals/migrations/0025_add_lease_status.py`
- `rentals/migrations/0026_set_existing_leases_active.py`

## Rollback Strategy

### If Issues Occur:

1. **Database Rollback:**
   ```bash
   python manage.py migrate rentals 0024  # Rollback to before status field
   ```

2. **Code Rollback:**
   - Revert `rentals/models.py` to remove status field and methods
   - Revert `rentals/services.py` to remove LeaseActivationService
   - Revert `accounts/admin_portal_views.py` to original lease creation
   - Revert `payments/views.py` to original webhook
   - Revert `rentals/views.py` to original tenant dashboard
   - Revert `billing/services.py` to original payment approval

3. **Quick Fix (if migration applied but code not working):**
   - Manually update all leases: `Lease.objects.all().update(is_active=True)`
   - This restores old behavior temporarily

### Rollback Commands:
```bash
# Full rollback
git revert HEAD~3  # Reverts last 3 commits
python manage.py migrate rentals 0024

# Or manual rollback
git checkout <commit-before-implementation>
python manage.py migrate rentals 0024
```

## Testing Checklist

- [ ] Create new lease → Status = PENDING_PAYMENT
- [ ] Unit remains AVAILABLE after lease creation
- [ ] No bills generated after lease creation
- [ ] Payment page shows lease summary correctly
- [ ] PayMongo payment → Webhook activates lease
- [ ] GCash payment → Approval activates lease
- [ ] Cash payment → Immediate activation
- [ ] Unit becomes OCCUPIED after payment
- [ ] Billing generates after activation
- [ ] First bill marked PAID after activation
- [ ] Tenant can see pending lease in dashboard
- [ ] Tenant cannot see bills for pending lease
- [ ] Admin dashboard counts correct (ACTIVE only)
- [ ] Duplicate webhook calls don't reactivate lease
- [ ] Cancelled payment doesn't activate lease
- [ ] Existing leases still work (status='ACTIVE')

## Regression Risks

### Low Risk:
- Unit.is_active queries (unchanged)
- Announcement queries (unchanged)
- Most admin views (only dashboard changed)

### Medium Risk:
- Admin dashboard counts (now uses status field)
- Tenant dashboard queries (now includes pending leases)
- Payment approval flow (now checks for pending leases)

### High Risk:
- None identified - all changes are additive with backward compatibility

## Safety Features

1. **Idempotent Activation:** Service checks if already active before activating
2. **Transaction Safety:** All activation steps in single transaction
3. **Fallback Logic:** Payment approval has fallback if activation fails
4. **Backward Compatibility:** is_active field still synced with status
5. **Migration Safety:** Existing leases set to ACTIVE status

## Next Steps

1. Test full flow with PayMongo
2. Test full flow with GCash
3. Test full flow with Cash
4. Verify existing leases still work
5. Verify reports are accurate
6. Deploy to staging for user testing
