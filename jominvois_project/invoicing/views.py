import csv
from decimal import Decimal

from django.contrib import messages
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .models import (
    AuditLog,
    InvoiceDraft,
    OrbyteCustomer,
    OrbyteProduct,
)
from .services import parse_whatsapp_order, validate_lhdn_readiness

def dashboard_view(request):
    request.session.setdefault("orbyte_role", "STAFF")

    context = {
        "current_role": request.session.get("orbyte_role", "STAFF"),
        "drafts": (
            InvoiceDraft.objects
            .select_related("customer")
            .prefetch_related("logs")
            .all()
            .order_by("-created_at")
        ),
        "customers": OrbyteCustomer.objects.all().order_by("company_name"),
        "products": OrbyteProduct.objects.all().order_by("sku"),
    }

    return render(request, "invoicing/dashboard.html", context)


@require_POST
def switch_role_view(request):
    new_role = request.POST.get("role", "STAFF")
    if new_role not in {"STAFF", "OWNER"}:
        messages.error(request, "Unknown demo role. The previous role was retained.")
    else:
        request.session["orbyte_role"] = new_role
    return redirect("dashboard")


@require_POST
def simulate_whatsapp_view(request):
    cust_id = request.POST.get("customer_id")
    message = (request.POST.get("message") or "").strip()
    customer = OrbyteCustomer.objects.filter(pk=cust_id).first() if cust_id else None

    if not message:
        messages.error(request, "Enter a simulated order message first.")
        return redirect("dashboard")

    parsed_data = parse_whatsapp_order(message, customer)
    draft = InvoiceDraft.objects.create(
        customer=customer,
        raw_whatsapp_text=message,
        parsed_items_json=parsed_data["items"],
        invoice_type=parsed_data["invoice_type"],
        total_amount=parsed_data["total"],
        status="ACTION_REQUIRED",
        validation_errors=[],
    )

    AuditLog.objects.create(
        invoice=draft,
        actor_role="SYSTEM",
        action_description=(
            f"Received simulated order from {customer.company_name if customer else 'unconfirmed customer'}. "
            f"Parsed {len(parsed_data['items'])} catalogue/order line(s)."
        ),
    )

    # Record parser source, matching results and confidence for the demo audit trail.
    parsed_items = parsed_data.get("items", [])
    parser_name = parsed_data.get("parser", "deterministic")

    matched_count = sum(
        1
        for item in parsed_items
        if item.get("match_status") == "MATCHED" and item.get("sku")
    )
    review_count = len(parsed_items) - matched_count

    confidence_scores = []
    for item in parsed_items:
        try:
            score = float(item.get("confidence"))
        except (TypeError, ValueError):
            continue

        if 0.0 <= score <= 1.0:
            confidence_scores.append(score)

    summary = (
        f"Parser used: {parser_name}. "
        f"Extracted {len(parsed_items)} line(s); "
        f"{matched_count} matched; "
        f"{review_count} require manual review."
    )

    if confidence_scores:
        average_confidence = (
            sum(confidence_scores) / len(confidence_scores)
        )
        summary += f" Average item confidence: {average_confidence:.2f}."

    AuditLog.objects.create(
        invoice=draft,
        actor_role="SYSTEM / PARSER",
        action_description=summary,
    )

    # Record the result for each parsed order line.
    for index, item in enumerate(parsed_items, start=1):
        description = str(
            item.get("raw_description")
            or item.get("name")
            or "Unknown item"
        )
        description = " ".join(description.split())[:120]

        sku = (
            item.get("sku")
            or item.get("suggested_sku")
            or "UNMATCHED"
        )
        status = item.get("match_status", "UNKNOWN")
        method = item.get("match_method", parser_name)

        try:
            confidence = float(item.get("confidence"))
            confidence_text = (
                f"{confidence:.2f}"
                if 0.0 <= confidence <= 1.0
                else "unavailable"
            )
        except (TypeError, ValueError):
            confidence_text = "unavailable"

        AuditLog.objects.create(
            invoice=draft,
            actor_role="SYSTEM / PARSER",
            action_description=(
                f"Line {index}: '{description}' -> SKU {sku}; "
                f"status={status}; confidence={confidence_text}; "
                f"method={method}."
            ),
        )

    rule_logs = validate_lhdn_readiness(draft, parse_errors=parsed_data["parse_errors"])
    for log in rule_logs:
        AuditLog.objects.create(invoice=draft, actor_role="SYSTEM / READINESS CHECK", action_description=log)

    if draft.status == "READY":
        messages.success(request, f"Draft #{draft.id} is ready for owner review.")
    else:
        messages.warning(request, f"Draft #{draft.id} needs attention before it can be approved.")
    return redirect("dashboard")

@require_POST
def resolve_invoice_view(request, draft_id):
    """
    Allow staff or owner to correct a synthetic draft before approval.

    This resolves catalogue/customer issues in our local demo data.
    It does not connect to Orbyte or submit anything to LHDN/MyInvois.
    """
    draft = get_object_or_404(InvoiceDraft, pk=draft_id)

    # Approved drafts are read-only.
    if draft.status == "APPROVED":
        messages.error(request, "Approved drafts cannot be edited.")
        return redirect("dashboard")

    # 1. Validate the selected customer.
    customer_id = (request.POST.get("customer_id") or "").strip()

    try:
        customer_pk = int(customer_id)
    except (TypeError, ValueError):
        messages.error(request, "Please select a valid synthetic customer.")
        return redirect("dashboard")

    customer = OrbyteCustomer.objects.filter(pk=customer_pk).first()

    if customer is None:
        messages.error(request, "The selected customer does not exist.")
        return redirect("dashboard")

    # 2. Require explicit confirmation of the draft workflow category.
    workflow_type = (request.POST.get("invoice_type") or "").strip()

    if workflow_type not in {"B2B", "B2C"}:
        messages.error(
            request,
            "Please confirm the draft workflow as B2B or B2C before continuing.",
        )
        return redirect("dashboard")

    # Do not silently override an explicitly known synthetic customer type.
    if (
        customer.customer_type in {"B2B", "B2C"}
        and workflow_type != customer.customer_type
    ):
        messages.error(
            request,
            "The selected workflow conflicts with the customer's "
            "synthetic profile. Select the correct customer or workflow.",
        )
        return redirect("dashboard")

    current_items = draft.parsed_items_json

    if not isinstance(current_items, list) or not current_items:
        messages.error(
            request,
            "This draft has no parsed order lines to resolve.",
        )
        return redirect("dashboard")

    # 3. Validate every SKU and quantity before making any changes.
    new_items = []
    new_total = Decimal("0.00")
    catalogue = {
        product.sku: product
        for product in OrbyteProduct.objects.all()
    }

    for index, old_item in enumerate(current_items):
        sku = (request.POST.get(f"item_sku_{index}") or "").strip()
        raw_qty = (request.POST.get(f"item_qty_{index}") or "").strip()

        product = catalogue.get(sku)

        if product is None:
            messages.error(
                request,
                f"Please select a valid catalogue product for line {index + 1}.",
            )
            return redirect("dashboard")

        try:
            quantity = int(raw_qty)
        except (TypeError, ValueError):
            messages.error(
                request,
                f"Enter a whole-number quantity for {product.name}.",
            )
            return redirect("dashboard")

        if quantity <= 0:
            messages.error(
                request,
                f"Quantity for {product.name} must be greater than zero.",
            )
            return redirect("dashboard")

        unit_price = product.unit_price.quantize(Decimal("0.01"))
        line_total = (
            unit_price * Decimal(quantity)
        ).quantize(Decimal("0.01"))

        # Keep the original description for auditability.
        updated_item = dict(old_item)
        updated_item.update({
            "sku": product.sku,
            "name": product.name,
            "raw_description": old_item.get(
                "raw_description",
                old_item.get("name", ""),
            ),
            "qty": quantity,
            "unit_price": str(unit_price),
            "line_total": str(line_total),
            "classification_code": product.classification_code,
            "match_status": "MATCHED",
            "match_method": "MANUAL_CONFIRMED",
        })

        new_items.append(updated_item)
        new_total += line_total

    new_total = new_total.quantize(Decimal("0.01"))

    # 4. Save the corrections and rerun readiness validation atomically.
    actor_role = request.session.get("orbyte_role", "STAFF")
    actor_label = (
        "SME OWNER (simulated)"
        if actor_role == "OWNER"
        else "SALES STAFF (simulated)"
    )

    with transaction.atomic():
        draft.customer = customer
        draft.invoice_type = workflow_type
        draft.parsed_items_json = new_items
        draft.total_amount = new_total
        draft.validation_errors = []

        draft.save(update_fields=[
            "customer",
            "invoice_type",
            "parsed_items_json",
            "total_amount",
            "validation_errors",
        ])

        AuditLog.objects.create(
            invoice=draft,
            actor_role=actor_label,
            action_description=(
                f"Updated draft using customer profile "
                f"'{customer.company_name}', confirmed workflow "
                f"{workflow_type}, and manually confirmed "
                f"{len(new_items)} catalogue line(s)."
            ),
        )

        for index, item in enumerate(new_items, start=1):
            description = str(
                item.get("raw_description")
                or item.get("name")
                or "Unknown item"
            )
            description = " ".join(description.split())[:120]

            AuditLog.objects.create(
                invoice=draft,
                actor_role=actor_label,
                action_description=(
                    f"Manual resolution line {index}: "
                    f"'{description}' confirmed as "
                    f"{item['sku']} ({item['name']}), "
                    f"quantity={item['qty']}, "
                    f"unit_price=RM {item['unit_price']}."
                ),
            )

        # Do not reuse stale parser errors after the user has corrected them.
        rule_logs = validate_lhdn_readiness(
            draft,
            parse_errors=[],
        )

        for log in rule_logs:
            AuditLog.objects.create(
                invoice=draft,
                actor_role="SYSTEM / READINESS CHECK",
                action_description=log,
            )

    draft.refresh_from_db()

    if draft.status == "READY":
        messages.success(
            request,
            f"Draft #{draft.id} passed the demo readiness check "
            "and is ready for Owner review.",
        )
    else:
        messages.warning(
            request,
            f"Draft #{draft.id} was updated, but some issues remain. "
            "Review the latest validation messages.",
        )

    return redirect("dashboard")

@require_POST
def approve_invoice_view(request, draft_id):
    if request.session.get("orbyte_role", "STAFF") != "OWNER":
        return HttpResponse("Unauthorized: only the simulated SME Owner role can approve handover.", status=403)

    draft = get_object_or_404(InvoiceDraft, pk=draft_id)
    if draft.status != "READY":
        return HttpResponse(
            f"Draft #{draft.id} cannot be approved because its current status is {draft.get_status_display()}. "
            "Resolve all validation issues and rerun the readiness check first.",
            status=400,
        )

    draft.status = "APPROVED"
    draft.save(update_fields=["status"])
    AuditLog.objects.create(
        invoice=draft,
        actor_role="OWNER (simulated)",
        action_description=f"Approved Draft #{draft.id} for accountant handover. No LHDN filing was submitted.",
    )
    messages.success(request, f"Draft #{draft.id} was approved for accountant handover.")
    return redirect("dashboard")


def _csv_safe(value):
    """Avoid spreadsheet formula execution for text fields in exported CSV."""
    if value is None:
        return ""
    text = str(value)
    if text.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + text
    return text


def export_accountant_csv(request):
    """Export approved synthetic demo drafts for accountant review only."""
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="JomInvois_Accountant_Handover.csv"'
    response.write("\ufeff")  # Excel-friendly UTF-8 BOM.

    writer = csv.writer(response)
    writer.writerow([
        "Draft ID", "Draft Type", "Customer Name", "Buyer TIN (synthetic)",
        "Buyer BRN (synthetic)", "Total Amount (RM)", "Status", "Owner Approved",
        "Raw Order Message", "Validation Note",
    ])
    approved_drafts = InvoiceDraft.objects.filter(status="APPROVED").select_related("customer").order_by("created_at")
    for draft in approved_drafts:
        customer = draft.customer
        writer.writerow([
            draft.id,
            draft.get_invoice_type_display(),
            _csv_safe(customer.company_name if customer else "Unconfirmed customer"),
            _csv_safe(customer.tin_number if customer and customer.tin_number else ""),
            _csv_safe(customer.brn_number if customer and customer.brn_number else ""),
            str(Decimal(draft.total_amount).quantize(Decimal("0.01"))),
            draft.get_status_display(),
            "Yes (simulated role)",
            _csv_safe(draft.raw_whatsapp_text),
            "Synthetic demo readiness only; not an official LHDN/MyInvois validation or submission.",
        ])
    return response

def export_accountant_json(request):
    """
    Export approved synthetic drafts as an accountant handover summary.

    This is a custom summary JSON, not an official LHDN/MyInvois
    invoice payload and not a UBL 2.1 document.
    """
    drafts = list(
        InvoiceDraft.objects
        .filter(status="APPROVED")
        .select_related("customer")
        .prefetch_related("logs")
        .order_by("created_at", "id")
    )

    export_data = []

    for draft in drafts:
        customer = draft.customer

        customer_data = None
        if customer:
            customer_data = {
                "company_name": customer.company_name,
                "customer_type": customer.customer_type,
                "tin": customer.tin_number or None,
                "brn": customer.brn_number or None,
                "msic_code": getattr(customer, "msic_code", None) or None,
            }

        items = []

        for item in draft.parsed_items_json or []:
            items.append({
                "sku": item.get("sku"),
                "description": (
                    item.get("name")
                    or item.get("raw_description")
                    or "Unspecified item"
                ),
                "quantity": item.get("qty"),
                "unit_price_rm": item.get("unit_price"),
                "line_total_rm": item.get("line_total"),
                "classification_code": item.get(
                    "classification_code"
                ),
                "match_status": item.get("match_status"),
            })

        audit_trail = []

        for log in draft.logs.all().order_by("timestamp", "id"):
            audit_trail.append({
                "timestamp": timezone.localtime(
                    log.timestamp
                ).isoformat(),
                "actor": log.actor_role,
                "action": log.action_description,
            })

        export_data.append({
            "draft_id": draft.pk,
            "created_at": timezone.localtime(
                draft.created_at
            ).isoformat(),
            "status": draft.status,
            "workflow_type": draft.invoice_type,
            "customer": customer_data,
            "source_order_message": draft.raw_whatsapp_text,
            "items": items,
            "total_amount_rm": format(
                draft.total_amount,
                ".2f",
            ),
            "validation_notes": draft.validation_errors or [],
            "approval_note": (
                "Approved using the simulated SME Owner role. "
                "No live LHDN/MyInvois filing was submitted."
            ),
            "audit_trail": audit_trail,
        })

    payload = {
        "schema_version": "1.0",
        "product": "JomInvois",
        "export_type": "ACCOUNTANT_HANDOVER_SUMMARY",
        "generated_at": timezone.localtime().isoformat(),
        "draft_count": len(export_data),
        "disclaimer": (
            "Synthetic hackathon demonstration data only. "
            "This summary is not an official LHDN/MyInvois validation "
            "result, invoice submission, or UBL 2.1 payload."
        ),
        "drafts": export_data,
    }

    response = JsonResponse(
        payload,
        json_dumps_params={
            "indent": 2,
            "ensure_ascii": False,
        },
    )

    response["Content-Disposition"] = (
        'attachment; filename="JomInvois_Accountant_Handover.json"'
    )

    return response
