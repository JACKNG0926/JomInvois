import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("invoicing", "0001_initial")]

    operations = [
        migrations.AddField(
            model_name="orbytecustomer",
            name="customer_type",
            field=models.CharField(
                choices=[
                    ("B2B", "Business buyer (synthetic profile)"),
                    ("B2C", "Individual / walk-in buyer (synthetic profile)"),
                    ("UNKNOWN", "Unconfirmed buyer type"),
                ],
                default="UNKNOWN",
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name="invoicedraft",
            name="validation_errors",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AlterField(
            model_name="invoicedraft",
            name="customer",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to="invoicing.orbytecustomer"),
        ),
        migrations.AlterField(
            model_name="invoicedraft",
            name="invoice_type",
            field=models.CharField(
                choices=[
                    ("B2B", "B2B review draft"),
                    ("B2C", "B2C / consolidated review draft"),
                    ("UNKNOWN", "Buyer type requires confirmation"),
                ],
                default="UNKNOWN",
                max_length=12,
            ),
        ),
        migrations.AlterField(
            model_name="invoicedraft",
            name="status",
            field=models.CharField(
                choices=[
                    ("PENDING_TIN", "Pending Buyer Information"),
                    ("READY", "Ready for Owner Approval"),
                    ("APPROVED", "Approved for Accountant Handover"),
                    ("DISCREPANCY", "Catalogue / Stock Discrepancy"),
                    ("ACTION_REQUIRED", "Action Required"),
                ],
                default="ACTION_REQUIRED",
                max_length=20,
            ),
        ),
    ]
