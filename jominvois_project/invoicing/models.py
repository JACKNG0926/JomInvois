from django.db import models


class OrbyteCustomer(models.Model):
    CUSTOMER_TYPES = [
        ("B2B", "Business buyer (synthetic profile)"),
        ("B2C", "Individual / walk-in buyer (synthetic profile)"),
        ("UNKNOWN", "Unconfirmed buyer type"),
    ]

    company_name = models.CharField(max_length=255)
    phone_number = models.CharField(max_length=50, unique=True)
    customer_type = models.CharField(max_length=10, choices=CUSTOMER_TYPES, default="UNKNOWN")
    tin_number = models.CharField(max_length=50, blank=True, null=True)  # synthetic LHDN-related test value
    brn_number = models.CharField(max_length=50, blank=True, null=True)  # synthetic business registration test value
    msic_code = models.CharField(max_length=10, default="02200")
    address = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.company_name} ({self.phone_number})"


class OrbyteProduct(models.Model):
    sku = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=255)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    stock_qty = models.IntegerField(default=100)
    classification_code = models.CharField(max_length=10, default="022")

    def __str__(self):
        return f"[{self.sku}] {self.name} - RM {self.unit_price}"


class InvoiceDraft(models.Model):
    INVOICE_TYPES = [
        ("B2B", "B2B review draft"),
        ("B2C", "B2C / consolidated review draft"),
        ("UNKNOWN", "Buyer type requires confirmation"),
    ]
    STATUS_CHOICES = [
        ("PENDING_TIN", "Pending Buyer Information"),
        ("READY", "Ready for Owner Approval"),
        ("APPROVED", "Approved for Accountant Handover"),
        ("DISCREPANCY", "Catalogue / Stock Discrepancy"),
        ("ACTION_REQUIRED", "Action Required"),
    ]

    customer = models.ForeignKey(OrbyteCustomer, on_delete=models.SET_NULL, null=True, blank=True)
    raw_whatsapp_text = models.TextField()
    parsed_items_json = models.JSONField(default=list)
    validation_errors = models.JSONField(default=list, blank=True)
    invoice_type = models.CharField(max_length=12, choices=INVOICE_TYPES, default="UNKNOWN")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="ACTION_REQUIRED")
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Draft #{self.id} - {self.status}"


class AuditLog(models.Model):
    invoice = models.ForeignKey(InvoiceDraft, on_delete=models.CASCADE, related_name="logs")
    timestamp = models.DateTimeField(auto_now_add=True)
    actor_role = models.CharField(max_length=50)  # simulated roles for the hackathon prototype
    action_description = models.TextField()

    def __str__(self):
        return f"[{self.timestamp.strftime('%H:%M:%S')}] {self.actor_role}: {self.action_description}"
