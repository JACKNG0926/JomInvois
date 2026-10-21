from django.contrib import admin

from .models import AuditLog, InvoiceDraft, OrbyteCustomer, OrbyteProduct


@admin.register(OrbyteCustomer)
class OrbyteCustomerAdmin(admin.ModelAdmin):
    list_display = ("company_name", "customer_type", "tin_number", "brn_number")
    search_fields = ("company_name", "phone_number", "tin_number", "brn_number")
    list_filter = ("customer_type",)


@admin.register(OrbyteProduct)
class OrbyteProductAdmin(admin.ModelAdmin):
    list_display = ("sku", "name", "unit_price", "stock_qty", "classification_code")
    search_fields = ("sku", "name")


@admin.register(InvoiceDraft)
class InvoiceDraftAdmin(admin.ModelAdmin):
    list_display = ("id", "customer", "invoice_type", "status", "total_amount", "created_at")
    list_filter = ("invoice_type", "status")
    search_fields = ("raw_whatsapp_text",)
    readonly_fields = ("created_at",)


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("invoice", "timestamp", "actor_role", "action_description")
    readonly_fields = ("invoice", "timestamp", "actor_role", "action_description")
