from decimal import Decimal

from django.core.management.base import BaseCommand

from invoicing.models import OrbyteCustomer, OrbyteProduct


class Command(BaseCommand):
    help = "Create/update JomInvois synthetic demo customers and products. No real data is used."

    def handle(self, *args, **options):
        customers = [
            {
                "phone_number": "SYNTHETIC-CONTACT-B2B-READY",
                "company_name": "TEST B2B Buyer - Complete Profile",
                "customer_type": "B2B",
                "tin_number": "TEST-TIN-B2B-001",
                "brn_number": "TEST-BRN-B2B-001",
                "msic_code": "TEST-MSIC-001",
                "address": "Synthetic demo address - not a real company",
            },
            {
                "phone_number": "SYNTHETIC-CONTACT-B2B-MISSING",
                "company_name": "TEST B2B Buyer - Missing Tax Information",
                "customer_type": "B2B",
                "tin_number": "",
                "brn_number": "",
                "msic_code": "TEST-MSIC-002",
                "address": "Synthetic demo address - not a real company",
            },
            {
                "phone_number": "SYNTHETIC-CONTACT-B2C-WALKIN",
                "company_name": "TEST Walk-in Consumer",
                "customer_type": "B2C",
                "tin_number": "",
                "brn_number": "",
                "msic_code": "TEST-MSIC-003",
                "address": "Synthetic demo address - not a real person",
            },
            {
                "phone_number": "SYNTHETIC-CONTACT-UNKNOWN",
                "company_name": "TEST Buyer - Type Unconfirmed",
                "customer_type": "UNKNOWN",
                "tin_number": "",
                "brn_number": "",
                "msic_code": "TEST-MSIC-004",
                "address": "Synthetic demo address - not a real company or person",
            },
        ]
        for row in customers:
            key = row["phone_number"]
            defaults = {field: value for field, value in row.items() if field != "phone_number"}
            OrbyteCustomer.objects.update_or_create(phone_number=key, defaults=defaults)

        products = [
            {
                "sku": "SKU-101",
                "name": "Susu Pekat 1.5kg carton",
                "unit_price": Decimal("120.00"),
                "stock_qty": 1000,
                "classification_code": "022",
            },
            {
                "sku": "SKU-204",
                "name": "Kopi O Kaw bag",
                "unit_price": Decimal("45.00"),
                "stock_qty": 1000,
                "classification_code": "022",
            },
        ]
        for row in products:
            OrbyteProduct.objects.update_or_create(sku=row["sku"], defaults=row)

        self.stdout.write(self.style.SUCCESS(
            f"Synthetic demo data ready: {OrbyteCustomer.objects.count()} customers, "
            f"{OrbyteProduct.objects.count()} products. All records are fictional test data."
        ))
