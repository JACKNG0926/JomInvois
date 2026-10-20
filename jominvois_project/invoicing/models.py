from django.db import models

class OrbyteCustomer(models.Model):
    company_name = models.CharField(max_length=255)
    phone_number = models.CharField(max_length=50, unique=True)
    tin_number = models.CharField(max_length=50, blank=True, null=True)  # LHDN TIN
    brn_number = models.CharField(max_length=50, blank=True, null=True)  # Business Reg No
    msic_code = models.CharField(max_length=10, default="02200")        # Economic Activity Code
    address = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.company_name} ({self.phone_number})"

class OrbyteProduct(models.Model):
    sku = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=255)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    stock_qty = models.IntegerField(default=100)
    classification_code = models.CharField(max_length=10, default="022") # LHDN Item Code

    def __str__(self):
        return f"[{self.sku}] {self.name} - RM {self.unit_price}"

class InvoiceDraft(models.Model):
    INVOICE_TYPES = [
        ('B2B', 'B2B Individual e-Invoice'),
        ('B2C', 'B2C Consolidated Summary'),
    ]
    STATUS_CHOICES = [
        ('PENDING_TIN', 'Pending Customer TIN / Info'),
        ('READY', 'Ready for Owner Approval'),
        ('APPROVED', 'Approved & Ready for Accountant'),
        ('DISCREPANCY', 'Stock / Price Discrepancy Flagged'),
    ]

    customer = models.ForeignKey(OrbyteCustomer, on_delete=models.CASCADE, null=True, blank=True)
    raw_whatsapp_text = models.TextField()
    parsed_items_json = models.JSONField(default=list)
    invoice_type = models.CharField(max_length=3, choices=INVOICE_TYPES, default='B2B')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='READY')
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Draft #{self.id} - {self.status}"

class AuditLog(models.Model):
    invoice = models.ForeignKey(InvoiceDraft, on_delete=models.CASCADE, related_name='logs')
    timestamp = models.DateTimeField(auto_now_add=True)
    actor_role = models.CharField(max_length=50) # 'SYSTEM', 'SALES_STAFF', 'SME_OWNER'
    action_description = models.TextField()

    def __str__(self):
        return f"[{self.timestamp.strftime('%H:%M:%S')}] {self.actor_role}: {self.action_description}"