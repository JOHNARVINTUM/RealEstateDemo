# Database Seeding for ML Thesis Research

This document explains how to use the database seeding commands to generate realistic historical data for machine learning research.

## Overview

The seeder creates a comprehensive dataset for 58 apartment units with 36 months of historical data, specifically designed for:
- **SARIMA forecasting**: Monthly revenue, collections, and water consumption
- **Random Forest prediction**: Payment risk classification
- **NLP classification**: Maintenance request categorization

## Commands

### 1. seed_thesis_data

Main seeding command that creates the complete dataset.

```bash
python manage.py seed_thesis_data [options]
```

#### Required Options

- `--reset`: Required to delete existing demo data before generation

#### Optional Options

- `--dry-run`: Show what would be created without making changes
- `--months N`: Number of months of history to generate (default: 36)
- `--seed N`: Random seed for reproducible output (default: 360)
- `--units-only`: Only create units and tenants
- `--billing-only`: Only generate billing data (requires existing units/leases)
- `--payments-only`: Only generate payment data (requires existing bills)
- `--maintenance-only`: Only generate maintenance data (requires existing units/leases)

#### Usage Examples

```bash
# Dry run to see what would be created
python manage.py seed_thesis_data --dry-run

# Full dataset generation (requires --reset for safety)
python manage.py seed_thesis_data --reset --months 36 --seed 360

# Generate only units and tenants
python manage.py seed_thesis_data --reset --units-only

# Add billing data to existing units
python manage.py seed_thesis_data --billing-only --months 24
```

### 2. export_ml_datasets

Export ML-ready CSV files from the generated dataset.

```bash
python manage.py export_ml_datasets [options]
```

#### Optional Options

- `--output-dir PATH`: Output directory for CSV files (default: exports/ml)
- `--months N`: Number of months of history to export (default: 36)

#### Usage Examples

```bash
# Export all datasets to default location
python manage.py export_ml_datasets

# Export to custom directory
python manage.py export_ml_datasets --output-dir data/ml --months 24
```

## Generated Data Structure

### Units and Tenants
- **58 total units**: 39 occupied, 19 vacant
- **Unit types**: Studio (20), 1BR (25), 2BR (13)
- **Rent ranges**: ₱8,000-12,000 (Studio), ₱12,000-18,000 (1BR), ₱18,000-25,000 (2BR)
- **Fixed tenant names**: Uses provided list of 39 tenant names
- **Deterministic emails**: Format: firstname.lastname@example.com
- **Fixed password**: demo123 for all tenant accounts

### Billing and Payments
- **36 months of history**: 1,404 monthly bills (39 leases × 36 months)
- **Water consumption**: Realistic consumption 30-85 m³/month (average ~50 m³)
- **Water rate**: ₱45.00/m³
- **Payment behavior**: 
  - 76% pay on time
  - 17% pay slightly late (1-7 days)
  - 5% pay late (2-4 weeks)
  - 2% seriously delayed (>30 days)
- **Payment methods**: GCASH, CASH
- **Interest calculation**: 3% per week late

### Maintenance Requests
- **150-250 requests**: Randomly distributed across 36 months
- **Categories**: PLUMBING, ELECTRICAL, STRUCTURAL, OTHER
- **NLP labels**: Additional ML-ready labels for classification
- **Statuses**: OPEN, IN_PROGRESS, RESOLVED
- **Priorities**: LOW, MEDIUM, HIGH

## Exported Datasets

### SARIMA Datasets

1. **sarima_monthly_revenue.csv**
   - Monthly billing amounts (rent, water, interest)
   - Unit occupancy statistics
   - Occupancy rates

2. **sarima_collections.csv**
   - Monthly payment collections
   - Payment method breakdown
   - On-time vs late payments

3. **sarima_water_consumption.csv**
   - Total and average water consumption
   - Min/max consumption statistics
   - Seasonal data

### Random Forest Dataset

4. **random_forest_payment_risk.csv**
   - Tenant-month payment behavior
   - Historical payment patterns
   - Risk labels (LOW, MEDIUM, HIGH)
   - Features for ML training

### NLP Dataset

5. **nlp_maintenance_requests.csv**
   - Maintenance request descriptions
   - Database categories and ML labels
   - Request metadata (status, priority, dates)

## Safety Features

### Dry Run Mode
- `--dry-run` flag shows what would be created without making changes
- Validates the plan before execution
- Perfect for testing and verification

### Reset Protection
- `--reset` flag required for any destructive operations
- Preserves all admin/superuser accounts
- Only deletes demo data (tenants, units, leases, bills, etc.)

### Transaction Safety
- All operations wrapped in database transactions
- Rollback on any error
- Data integrity maintained

### Validation
- Comprehensive validation checks after generation
- Summary report with record counts
- Verification of expected data relationships

## Data Quality

### Realism
- Water consumption follows normal distribution (μ=50, σ=12)
- Payment behavior matches real-world patterns
- Rent ranges appropriate for unit types
- Maintenance requests use realistic descriptions

### Consistency
- Referential integrity maintained throughout
- One active lease per occupied unit
- No active leases for vacant units
- Proper bill-payment relationships

### Reproducibility
- Fixed random seed ensures consistent output
- Deterministic email generation
- Predictable data patterns

## Best Practices

1. **Always use --dry-run first** to verify the plan
2. **Backup production data** before using --reset
3. **Test with smaller datasets** using --months option
4. **Use partial seeding** for incremental development
5. **Validate exports** after generation
6. **Document custom seeds** for reproducibility

## Troubleshooting

### Common Issues

1. **Import errors**: Ensure all Django apps are properly installed
2. **Database locks**: Close admin panels during seeding
3. **Memory issues**: Use smaller --months for large datasets
4. **Validation failures**: Check existing data conflicts

### Solutions

```bash
# Check existing data
python manage.py shell
>>> from rentals.models import Unit, TenantProfile, Lease
>>> Unit.objects.count()
>>> TenantProfile.objects.count()
>>> Lease.objects.filter(is_active=True).count()

# Clear specific data types
python manage.py shell
>>> from billing.models import MonthlyBill
>>> MonthlyBill.objects.all().delete()

# Test with small dataset
python manage.py seed_thesis_data --dry-run --months 3 --seed 123
```

## File Structure

```
accounts/management/commands/
├── seed_thesis_data.py          # Main seeding command
└── export_ml_datasets.py        # ML export command

exports/ml/                      # Default export directory
├── sarima_monthly_revenue.csv
├── sarima_collections.csv
├── sarima_water_consumption.csv
├── random_forest_payment_risk.csv
└── nlp_maintenance_requests.csv
```

## Support

For issues or questions:
1. Check Django logs for error details
2. Verify database connections and permissions
3. Ensure sufficient disk space for exports
4. Test with dry-run mode first
