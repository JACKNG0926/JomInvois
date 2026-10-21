from .llm_parser import extract_order_with_llm
"""Deterministic, offline-safe services for the JomInvois prototype.

This module performs a *demo readiness check*, not an official LHDN/MyInvois
validation and never submits statutory filings.
"""
from decimal import Decimal
import re

from .models import OrbyteProduct


# Deliberately small alias set for the synthetic challenge catalogue. Extend
# these with aliases that the team has tested; do not guess unknown SKUs.
PRODUCT_ALIASES = {
    "SKU-101": ("susu pekat", "condensed milk"),
    "SKU-204": ("kopi o kaw", "kopi o", "kopi"),
}

QUANTITY_RE = re.compile(
    r"(?<!\w)(\d+)\s*(?:cartons?|ctn|bags?|packs?|boxes?|box|units?|pcs?|pieces?|"
    r"bottles?|botol|kotak|beg)\b|(?<!\w)x\s*(\d+)\b",
    re.IGNORECASE,
)
ANY_NUMBER_RE = re.compile(r"(?<![\w.])(\d+)(?![\w.])")
SEGMENT_RE = re.compile(r"\s*(?:,|&|;|\n|\b(?:and|dan)\b)\s*", re.IGNORECASE)


def _normalise(value):
    return re.sub(r"\s+", " ", (value or "").casefold()).strip()


def _segments(message_text):
    return [part.strip(" \t.!?-") for part in SEGMENT_RE.split(message_text or "") if part.strip(" \t.!?-")]

def _normalise_llm_result(payload, customer, products):
    """
    Convert untrusted LLM output into our application's item schema.

    The catalogue remains authoritative for SKU and price.
    Uncertain matches require manual confirmation.
    """
    raw_items = payload.get("items")

    if not isinstance(raw_items, list) or not raw_items:
        return None

    catalogue = {product.sku: product for product in products}
    items_found = []
    parse_errors = []

    for index, raw_item in enumerate(raw_items, start=1):
        description = str(raw_item.get("description") or "").strip()
        if not description:
            description = f"Unidentified order line {index}"

        # Limit what is stored from model output.
        description = description[:500]

        candidate_sku = raw_item.get("sku")
        if not isinstance(candidate_sku, str):
            candidate_sku = ""
        candidate_sku = candidate_sku.strip()

        product = catalogue.get(candidate_sku)

        try:
            confidence = float(raw_item.get("confidence", 0))
        except (TypeError, ValueError):
            confidence = 0.0

        if not 0.0 <= confidence <= 1.0:
            confidence = 0.0

        needs_confirmation = raw_item.get("needs_confirmation", True) is True

        raw_quantity = raw_item.get("quantity")
        quantity = None

        if (
            isinstance(raw_quantity, (int, float))
            and not isinstance(raw_quantity, bool)
            and float(raw_quantity).is_integer()
        ):
            parsed_quantity = int(raw_quantity)
            if 1 <= parsed_quantity <= 1_000_000:
                quantity = parsed_quantity

        # Require a known SKU, sufficiently high confidence and no
        # explicit request for human confirmation before accepting a match.
        matched = (
            product is not None
            and confidence >= 0.85
            and not needs_confirmation
        )

        if matched:
            unit_price = product.unit_price.quantize(Decimal("0.01"))

            line_total = None
            if quantity is not None:
                line_total = (
                    unit_price * Decimal(quantity)
                ).quantize(Decimal("0.01"))
            else:
                parse_errors.append(
                    f"Quantity is missing or unclear for {product.name}."
                )

            item = {
                "sku": product.sku,
                "name": product.name,
                "raw_description": description,
                "qty": quantity,
                "unit_price": str(unit_price),
                "line_total": (
                    str(line_total) if line_total is not None else None
                ),
                "classification_code": product.classification_code,
                "confidence": confidence,
                "match_status": "MATCHED",
                "match_method": "LLM_CATALOGUE_MATCH",
            }

        else:
            # Do not expose a questionable SKU as a confirmed match.
            item = {
                "sku": None,
                "suggested_sku": candidate_sku or None,
                "name": description,
                "raw_description": description,
                "qty": quantity,
                "unit_price": None,
                "line_total": None,
                "confidence": confidence,
                "match_status": "UNMATCHED",
                "match_method": "LLM_REQUIRES_REVIEW",
            }

            if product is None:
                parse_errors.append(
                    f"Could not match order line to a catalogue SKU: "
                    f"'{description}'."
                )
            else:
                parse_errors.append(
                    f"Catalogue match for '{description}' requires "
                    f"manual confirmation (confidence {confidence:.2f})."
                )

            if quantity is None:
                parse_errors.append(
                    f"Quantity is missing or unclear for '{description}'."
                )

        items_found.append(item)

    total = sum(
        (
            Decimal(item["line_total"])
            for item in items_found
            if item.get("line_total") is not None
            and item.get("match_status") == "MATCHED"
        ),
        Decimal("0.00"),
    ).quantize(Decimal("0.01"))

    return {
        "items": items_found,
        "total": total,
        "invoice_type": _invoice_type_for(customer),
        "parse_errors": list(dict.fromkeys(parse_errors)),
        "parser": "llm",
    }

def _quantity_from_segment(segment):
    """Return a positive integer quantity, or None when it is not clear."""
    match = QUANTITY_RE.search(segment)
    if match:
        quantity = int(match.group(1) or match.group(2))
        return quantity if quantity > 0 else None

    # Allow compact inputs like "Susu Pekat x 20" or "Susu Pekat 20".
    # A bare number is accepted only when there is exactly one integer in the
    # segment; this remains a demo parser and ambiguous text is sent to review.
    numbers = ANY_NUMBER_RE.findall(segment)
    if len(numbers) == 1:
        quantity = int(numbers[0])
        return quantity if quantity > 0 else None
    return None


def _match_product(segment, products):
    """Find a catalogue product using SKU, full name or known aliases."""
    text = _normalise(segment)
    candidates = []
    for product in products:
        aliases = [product.sku, product.name]
        aliases.extend(PRODUCT_ALIASES.get(product.sku.upper(), ()))
        for alias in aliases:
            normalized_alias = _normalise(alias)
            if normalized_alias and normalized_alias in text:
                candidates.append((len(normalized_alias), product))
    if not candidates:
        return None
    # Prefer the longest phrase (e.g. "kopi o kaw" over "kopi").
    candidates.sort(key=lambda candidate: candidate[0], reverse=True)
    return candidates[0][1]


def _has_quantity_unit(segment):
    return bool(QUANTITY_RE.search(segment))


def parse_whatsapp_order(message_text, customer):
    """Parse a WhatsApp-style message against the local synthetic catalogue.

    This is the deterministic fallback used by the MVP. It does not invent a
    generic SKU for unrecognised products: unclear lines are flagged for review.
    """
    message_text = (message_text or "").strip()
    products = list(OrbyteProduct.objects.all())
    items_found = []
    parse_errors = []

    # Optional LLM extraction. If disabled or unavailable, continue
    # with the deterministic parser already implemented below.
    if message_text:
        llm_payload = extract_order_with_llm(message_text, products)

        if llm_payload is not None:
            llm_result = _normalise_llm_result(
                llm_payload,
                customer,
                products,
            )

            if llm_result is not None:
                return llm_result

    if not message_text:
        return {
            "items": [],
            "total": Decimal("0.00"),
            "invoice_type": _invoice_type_for(customer),
            "parse_errors": ["Enter an order message before starting the workflow."],
        }

    for segment in _segments(message_text):
        product = _match_product(segment, products)
        if product is None:
            if _has_quantity_unit(segment):
                qty = _quantity_from_segment(segment)
                items_found.append({
                    "sku": None,
                    "name": segment,
                    "raw_description": segment,
                    "qty": qty,
                    "unit_price": None,
                    "line_total": None,
                    "confidence": 0.0,
                    "match_status": "UNMATCHED",
                })
                parse_errors.append(f"Could not match order line to a catalogue SKU: '{segment}'.")
            continue

        qty = _quantity_from_segment(segment)
        item = {
            "sku": product.sku,
            "name": product.name,
            "qty": qty,
            "unit_price": str(product.unit_price),
            "line_total": None,
            "classification_code": product.classification_code,
            "confidence": 1.0,
            "match_status": "MATCHED",
        }
        if qty is None:
            parse_errors.append(f"Quantity is missing or unclear for {product.name}.")
        else:
            line_total = (product.unit_price * Decimal(qty)).quantize(Decimal("0.01"))
            item["line_total"] = str(line_total)
        items_found.append(item)

    if not items_found:
        parse_errors.append("No recognisable catalogue item was found. Confirm the product manually.")

    total = sum(
        (Decimal(item["line_total"]) for item in items_found if item.get("line_total") is not None),
        Decimal("0.00"),
    ).quantize(Decimal("0.01"))

    return {
        "items": items_found,
        "total": total,
        "invoice_type": _invoice_type_for(customer),
        "parse_errors": list(dict.fromkeys(parse_errors)),
    }


def _invoice_type_for(customer):
    """Use the explicit synthetic customer profile, never tax-field presence alone."""
    if customer is None:
        return "UNKNOWN"
    customer_type = getattr(customer, "customer_type", "UNKNOWN")
    if customer_type == "B2B":
        return "B2B"
    if customer_type == "B2C":
        return "B2C"
    return "UNKNOWN"


def validate_lhdn_readiness(draft, parse_errors=None):
    """Apply conservative local checks to a draft; this is not LHDN validation."""
    parse_errors = list(parse_errors or [])
    errors = list(parse_errors)
    customer = draft.customer
    has_discrepancy = False
    has_action_issue = bool(parse_errors)
    missing_buyer_fields = []

    if not customer:
        errors.append("Customer profile is missing; select or confirm the customer.")
        has_action_issue = True
    if draft.invoice_type == "UNKNOWN":
        errors.append("Customer type is unknown; staff must confirm the correct workflow.")
        has_action_issue = True

    if not draft.parsed_items_json:
        errors.append("No order lines are ready for review.")
        has_action_issue = True

    for item in draft.parsed_items_json:
        if item.get("match_status") != "MATCHED" or not item.get("sku"):
            errors.append(f"Unmatched catalogue item requires manual confirmation: {item.get('name', 'Unknown item')}.")
            has_discrepancy = True
            continue
        qty = item.get("qty")
        if not isinstance(qty, int) or qty <= 0:
            errors.append(f"A valid positive quantity is required for {item.get('name', item.get('sku'))}.")
            has_action_issue = True
            continue
        product = OrbyteProduct.objects.filter(sku=item["sku"]).first()
        if not product:
            errors.append(f"Catalogue SKU {item['sku']} no longer exists; confirm the item manually.")
            has_discrepancy = True
        elif qty > product.stock_qty:
            errors.append(
                f"Requested quantity ({qty}) exceeds recorded demo stock ({product.stock_qty}) for {product.name}."
            )
            has_discrepancy = True

    if draft.invoice_type == "B2B":
        if not customer or not customer.tin_number:
            missing_buyer_fields.append("Buyer TIN is missing from the synthetic customer profile.")
        if not customer or not customer.brn_number:
            missing_buyer_fields.append("Buyer BRN is missing from the synthetic customer profile.")
        errors.extend(missing_buyer_fields)

    # Deduplicate while preserving the order in which issues were discovered.
    errors = list(dict.fromkeys(errors))
    if has_discrepancy:
        status = "DISCREPANCY"
    elif has_action_issue:
        status = "ACTION_REQUIRED"
    elif missing_buyer_fields:
        status = "PENDING_TIN"
    elif errors:
        status = "ACTION_REQUIRED"
    else:
        status = "READY"

    draft.status = status
    draft.validation_errors = errors
    draft.save(update_fields=["status", "validation_errors"])

    if errors:
        logs = [f"Readiness check: {error}" for error in errors]
    else:
        logs = [
            "Readiness check passed for this synthetic demo scenario. This is not official LHDN/MyInvois validation.",
            f"Customer profile explicitly routes the draft to {draft.invoice_type} review.",
        ]
    return logs
