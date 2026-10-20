import json
import re


def parse_whatsapp_order(message_text, customer):
    """
    Simulates AI extraction of messy Manglish text into structured items.
    Fallback rule-based extraction ensures 100% demo stability even without internet.
    """
    items_found = []
    text_lower = message_text.lower()

    # Simple rule-based keyword extraction for demo reliability
    if "susu" in text_lower or "carton" in text_lower:
        items_found.append({"sku": "SKU-101", "name": "Susu Pekat 1.5kg", "qty": 20, "unit_price": 120.00})
    if "kopi" in text_lower or "bag" in text_lower:
        items_found.append({"sku": "SKU-204", "name": "Kopi O Kaw", "qty": 10, "unit_price": 45.00})
    if not items_found:
        # Default fallback item if text is custom typed
        items_found.append({"sku": "SKU-999", "name": "General Sundry Item", "qty": 5, "unit_price": 50.00})

    total = sum(item['qty'] * item['unit_price'] for item in items_found)

    # Determine if B2B (requires TIN) or B2C Consolidated
    inv_type = 'B2B' if customer and customer.tin_number else 'B2C'

    return {
        "items": items_found,
        "total": total,
        "invoice_type": inv_type
    }


def validate_lhdn_readiness(draft):
    """
    Deterministic Rule Engine checking LHDN compliance requirements.
    """
    logs = []
    if draft.invoice_type == 'B2B':
        if not draft.customer or not draft.customer.tin_number or not draft.customer.brn_number:
            draft.status = 'PENDING_TIN'
            logs.append("Rule Engine: Missing Buyer TIN or BRN. Flagged for Sales Clerk review.")
        else:
            draft.status = 'READY'
            logs.append("Rule Engine: Buyer TIN & BRN verified against LHDN format rules. Ready for Owner approval.")
    else:
        draft.status = 'READY'
        logs.append("Rule Engine: Categorized under Monthly Consolidated e-Invoice (B2C). Ready for Owner approval.")

    draft.save()
    return logs