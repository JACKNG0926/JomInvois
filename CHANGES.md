# JomInvois code review changes

## Core workflow
- Replaced hard-coded order quantities and invented fallback SKUs with deterministic text parsing against the synthetic product catalogue.
- Added quantity parsing for common units (carton, bag, pack, box, unit, pcs, etc.). Unmatched items or unclear quantities are flagged for manual review.
- Uses `Decimal` for line totals and order totals.
- Routes B2B/B2C/unknown based on an explicit synthetic customer profile, not merely whether a TIN value exists.
- Added conservative statuses for `ACTION_REQUIRED`, missing buyer information, and catalogue/stock discrepancies.
- Readiness messages explicitly state that checks are synthetic demo checks, not official LHDN/MyInvois validation.

## Approval and records
- Approval now accepts POST only and requires the simulated Owner role.
- Only `READY` drafts may be approved; missing information, unknown customer type, unmatched items, invalid quantities, and stock discrepancies block approval.
- Added `validation_errors` to each draft and display those errors on the dashboard.
- CSV export includes approved drafts only, labels the data as synthetic, and protects exported text fields against common spreadsheet formula injection.

## Data and project hygiene
- Added `customer_type` to synthetic customer profiles.
- Added an idempotent `seed_demo_data` management command for fictional test customers and products.
- Added unit/integration tests for parsing, validation, role checks, approval gating, and CSV export.
- Added `requirements.txt`, a fuller README, `.gitignore`, and `.env.example`.
- Removed the duplicate ignored database configuration and moved Django secret/host settings to environment variables; set the time zone to Asia/Kuala_Lumpur.
- The dashboard now clearly states that the current version uses synthetic data and is not connected to live WhatsApp, Orbyte or MyInvois services.

## Validation performed here
- Python syntax/AST checks passed for the project's Python files.
- Offline parser/validation smoke tests passed against a small test harness.
- The full Django test suite could not be executed in this environment because Django is not installed here and network access to install dependencies is unavailable. Run `python manage.py test invoicing` in Replit or your local environment after installing `requirements.txt`.

## Remaining items for the team
- Run migrations and `seed_demo_data` in the new project environment.
- Run the Django test suite and fix any environment-specific errors before demo day.
- Obtain Orbyte workspace approval and use only documented/authorized integration capabilities. No live Orbyte integration is claimed in this ZIP.
- Confirm the Replit Core voucher status and then deploy with `DJANGO_SECRET_KEY`, `DJANGO_DEBUG=0`, and `DJANGO_ALLOWED_HOSTS` set in the environment.
- Declare every AI tool/model/API/host actually used in the official hackathon declaration.
