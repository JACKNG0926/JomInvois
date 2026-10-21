# JomInvois — Domain 2 MVP

JomInvois is a hackathon prototype for turning synthetic WhatsApp-style SME order messages into structured order drafts, checking core readiness fields, requiring simulated owner approval, and exporting an accountant handover CSV.

> **Prototype boundary:** all seeded records are fictional. This project does not connect to live WhatsApp or Orbyte services, does not provide tax/legal advice, does not perform official LHDN/MyInvois validation, and does not submit statutory filings or process payments.

## Requirements

- Python 3.11+ (the team's target environment may use Python 3.13)
- Django (install the pinned project range from `requirements.txt`)

## Local setup (Windows PowerShell)

From the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Set-Location .\jominvois_project
python manage.py migrate
python manage.py seed_demo_data
python manage.py test invoicing
python manage.py runserver
```

Open `http://127.0.0.1:8000/`.

## Local setup (macOS / Linux)

From the repository root:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cd jominvois_project
python manage.py migrate
python manage.py seed_demo_data
python manage.py test invoicing
python manage.py runserver
```

## Demo scenarios

The `seed_demo_data` command idempotently creates synthetic customers and catalogue products:

1. A B2B test profile with buyer fields present — a matched order should become `READY`.
2. A B2B test profile with missing buyer fields — the draft should be blocked as `PENDING_TIN`.
3. A B2C test profile — routing is based on the explicit synthetic customer profile, not merely whether a TIN exists.
4. An unconfirmed buyer profile — the workflow should stop at `ACTION_REQUIRED`.

Try these messages:

- `Boss, hantar 20 carton Susu Pekat & 10 bag Kopi O Kaw ya.`
- `Please send 5 carton Dragonfruit` (unmatched product; must not invent a SKU)
- `Please send Susu Pekat tomorrow` (quantity needs manual confirmation)

Use the synthetic customer selector to control the buyer profile. Role switching between `STAFF` and `OWNER` is a demonstration-only simulation, not production-grade authentication. Only `READY` drafts may be approved, and the approval endpoint accepts POST requests only.

## Data and readiness checks

- Product matching uses a deliberately small deterministic alias list; ambiguous or unknown lines require manual review.
- Money calculations use `Decimal`.
- Readiness checks are local demo checks only, not official LHDN/MyInvois validation.
- CSV export contains approved drafts only and warns that the output is for synthetic demo review.
- Customer/TIN/BRN-like values in the seed command are explicitly fictional placeholders.

## Orbyte integration

The current adapter boundary is not connected to a live Orbyte workspace. After the team's workspace is approved, integrate only with documented and authorized Orbyte capabilities/API details. Do not claim live integration until it has been tested. Keep synthetic data for the hackathon demo.

## Deployment configuration

Set `DJANGO_SECRET_KEY` to a secret environment value, set `DJANGO_DEBUG=0`, and set `DJANGO_ALLOWED_HOSTS` to the hostnames for your deployment. Do not commit secrets, production credentials, or real customer records.

## AI/tools declaration

Update the team's official Tech & Tools Declaration with every AI model, API, coding assistant, hosting service, dataset, and sponsor resource actually used. Team members should review and be able to explain all core code.
