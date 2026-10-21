from decimal import Decimal

from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from .models import AuditLog, InvoiceDraft, OrbyteCustomer, OrbyteProduct
from .services import parse_whatsapp_order, validate_lhdn_readiness


class JomInvoisServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ready_b2b = OrbyteCustomer.objects.create(
            company_name="TEST B2B Buyer - Complete",
            phone_number="SYNTHETIC-TEST-B2B-READY",
            customer_type="B2B",
            tin_number="TEST-TIN-001",
            brn_number="TEST-BRN-001",
        )
        cls.missing_b2b = OrbyteCustomer.objects.create(
            company_name="TEST B2B Buyer - Missing Info",
            phone_number="SYNTHETIC-TEST-B2B-MISSING",
            customer_type="B2B",
            tin_number="",
            brn_number="",
        )
        cls.walk_in = OrbyteCustomer.objects.create(
            company_name="TEST Walk-in Consumer",
            phone_number="SYNTHETIC-TEST-B2C",
            customer_type="B2C",
        )
        cls.unknown_customer = OrbyteCustomer.objects.create(
            company_name="TEST Buyer - Unknown Type",
            phone_number="SYNTHETIC-TEST-UNKNOWN",
            customer_type="UNKNOWN",
        )
        OrbyteProduct.objects.create(
            sku="SKU-101", name="Susu Pekat 1.5kg carton",
            unit_price=Decimal("120.00"), stock_qty=100, classification_code="022",
        )
        OrbyteProduct.objects.create(
            sku="SKU-204", name="Kopi O Kaw bag",
            unit_price=Decimal("45.00"), stock_qty=100, classification_code="022",
        )

    def make_draft(self, customer, message="20 carton Susu Pekat & 10 bag Kopi O Kaw"):
        parsed = parse_whatsapp_order(message, customer)
        draft = InvoiceDraft.objects.create(
            customer=customer,
            raw_whatsapp_text=message,
            parsed_items_json=parsed["items"],
            invoice_type=parsed["invoice_type"],
            total_amount=parsed["total"],
        )
        validate_lhdn_readiness(draft, parse_errors=parsed["parse_errors"])
        draft.refresh_from_db()
        return draft, parsed

    def test_extracts_each_quantity_and_calculates_with_decimal(self):
        parsed = parse_whatsapp_order("Boss, hantar 20 carton Susu Pekat & 10 bag Kopi O Kaw ya.", self.ready_b2b)
        self.assertEqual([item["qty"] for item in parsed["items"]], [20, 10])
        self.assertEqual([item["sku"] for item in parsed["items"]], ["SKU-101", "SKU-204"])
        self.assertEqual(parsed["total"], Decimal("2850.00"))

    def test_unknown_product_is_not_invented(self):
        parsed = parse_whatsapp_order("Please send 5 carton Dragonfruit", self.ready_b2b)
        self.assertEqual(parsed["total"], Decimal("0.00"))
        self.assertEqual(parsed["items"][0]["match_status"], "UNMATCHED")
        self.assertIsNone(parsed["items"][0]["sku"])
        draft = InvoiceDraft.objects.create(
            customer=self.ready_b2b, raw_whatsapp_text="Please send 5 carton Dragonfruit",
            parsed_items_json=parsed["items"], invoice_type=parsed["invoice_type"], total_amount=parsed["total"],
        )
        validate_lhdn_readiness(draft, parse_errors=parsed["parse_errors"])
        draft.refresh_from_db()
        self.assertEqual(draft.status, "DISCREPANCY")

    def test_missing_quantity_requires_action(self):
        draft, _ = self.make_draft(self.ready_b2b, "Please send Susu Pekat tomorrow")
        self.assertEqual(draft.status, "ACTION_REQUIRED")
        self.assertTrue(draft.validation_errors)

    def test_missing_b2b_tax_information_blocks_ready_status(self):
        draft, _ = self.make_draft(self.missing_b2b)
        self.assertEqual(draft.status, "PENDING_TIN")
        self.assertTrue(any("TIN" in error for error in draft.validation_errors))
        self.assertTrue(any("BRN" in error for error in draft.validation_errors))

    def test_b2b_complete_profile_is_ready_for_demo_review(self):
        draft, _ = self.make_draft(self.ready_b2b)
        self.assertEqual(draft.status, "READY")
        self.assertEqual(draft.invoice_type, "B2B")

    def test_b2c_classification_uses_explicit_profile_not_missing_tin(self):
        parsed = parse_whatsapp_order("5 carton Susu Pekat", self.walk_in)
        self.assertEqual(parsed["invoice_type"], "B2C")

    def test_unknown_customer_type_requires_action(self):
        draft, _ = self.make_draft(self.unknown_customer)
        self.assertEqual(draft.invoice_type, "UNKNOWN")
        self.assertEqual(draft.status, "ACTION_REQUIRED")


class JomInvoisViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.customer = OrbyteCustomer.objects.create(
            company_name="TEST B2B Buyer",
            phone_number="SYNTHETIC-VIEW-B2B",
            customer_type="B2B",
            tin_number="TEST-TIN-VIEW",
            brn_number="TEST-BRN-VIEW",
        )
        OrbyteProduct.objects.create(
            sku="SKU-101", name="Susu Pekat 1.5kg carton",
            unit_price=Decimal("120.00"), stock_qty=100, classification_code="022",
        )

    def create_ready_draft(self):
        response = self.client.post(reverse("simulate_whatsapp"), {
            "customer_id": self.customer.pk,
            "message": "20 carton Susu Pekat",
        })
        self.assertEqual(response.status_code, 302)
        return InvoiceDraft.objects.latest("id")

    def test_simulate_post_creates_draft_and_audit_log(self):
        self.client.post(reverse("simulate_whatsapp"), {
            "customer_id": self.customer.pk,
            "message": "20 carton Susu Pekat",
        })
        draft = InvoiceDraft.objects.latest("id")
        self.assertEqual(draft.total_amount, Decimal("2400.00"))
        self.assertGreaterEqual(AuditLog.objects.filter(invoice=draft).count(), 2)

    def test_empty_message_does_not_create_draft(self):
        response = self.client.post(reverse("simulate_whatsapp"), {
            "customer_id": self.customer.pk, "message": "   ",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(InvoiceDraft.objects.count(), 0)

    def test_approval_requires_post(self):
        draft = self.create_ready_draft()
        response = self.client.get(reverse("approve_invoice", args=[draft.pk]))
        self.assertEqual(response.status_code, 405)

    def test_staff_cannot_approve(self):
        draft = self.create_ready_draft()
        session = self.client.session
        session["orbyte_role"] = "STAFF"
        session.save()
        response = self.client.post(reverse("approve_invoice", args=[draft.pk]))
        self.assertEqual(response.status_code, 403)
        draft.refresh_from_db()
        self.assertEqual(draft.status, "READY")

    def test_owner_can_approve_ready_draft(self):
        draft = self.create_ready_draft()
        session = self.client.session
        session["orbyte_role"] = "OWNER"
        session.save()
        response = self.client.post(reverse("approve_invoice", args=[draft.pk]))
        self.assertEqual(response.status_code, 302)
        draft.refresh_from_db()
        self.assertEqual(draft.status, "APPROVED")
        self.assertTrue(AuditLog.objects.filter(invoice=draft, actor_role__startswith="OWNER").exists())

    def test_owner_cannot_approve_pending_draft(self):
        customer = OrbyteCustomer.objects.create(
            company_name="TEST Missing Buyer Info", phone_number="SYNTHETIC-PENDING-B2B",
            customer_type="B2B", tin_number="", brn_number="",
        )
        parsed = parse_whatsapp_order("2 carton Susu Pekat", customer)
        draft = InvoiceDraft.objects.create(
            customer=customer, raw_whatsapp_text="2 carton Susu Pekat", parsed_items_json=parsed["items"],
            invoice_type=parsed["invoice_type"], total_amount=parsed["total"],
        )
        validate_lhdn_readiness(draft, parsed["parse_errors"])
        draft.refresh_from_db()
        self.assertEqual(draft.status, "PENDING_TIN")
        session = self.client.session
        session["orbyte_role"] = "OWNER"
        session.save()
        response = self.client.post(reverse("approve_invoice", args=[draft.pk]))
        self.assertEqual(response.status_code, 400)
        draft.refresh_from_db()
        self.assertEqual(draft.status, "PENDING_TIN")

    def test_csv_exports_only_approved_drafts(self):
        draft = self.create_ready_draft()
        session = self.client.session
        session["orbyte_role"] = "OWNER"
        session.save()
        self.client.post(reverse("approve_invoice", args=[draft.pk]))
        response = self.client.get(reverse("export_csv"))
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Draft ID", response.content)
        self.assertIn(b"Approved for Accountant Handover", response.content)
        self.assertIn(b"not an official LHDN/MyInvois validation", response.content)

        class DraftResolutionViewTests(TestCase):
            def setUp(self):
                self.customer = OrbyteCustomer.objects.create(
                    company_name="TEST Resolution Buyer",
                    phone_number="SYNTHETIC-RESOLUTION-B2B",
                    customer_type="B2B",
                    tin_number="TEST-TIN-RESOLUTION",
                    brn_number="TEST-BRN-RESOLUTION",
                )

                self.product = OrbyteProduct.objects.create(
                    sku="SKU-101",
                    name="Susu Pekat 1.5kg carton",
                    unit_price=Decimal("120.00"),
                    stock_qty=100,
                    classification_code="022",
                )

                self.draft = InvoiceDraft.objects.create(
                    customer=None,
                    raw_whatsapp_text="Boss, bagi barang biasa 5 kotak",
                    parsed_items_json=[
                        {
                            "sku": None,
                            "name": "barang biasa 5 kotak",
                            "raw_description": "barang biasa 5 kotak",
                            "qty": 5,
                            "unit_price": None,
                            "line_total": None,
                            "confidence": 0.0,
                            "match_status": "UNMATCHED",
                        }
                    ],
                    invoice_type="UNKNOWN",
                    status="ACTION_REQUIRED",
                    total_amount=Decimal("0.00"),
                    validation_errors=[
                        "Customer profile is missing.",
                        "Unmatched catalogue item requires manual confirmation.",
                    ],
                )

            def test_staff_can_resolve_unmatched_draft(self):
                response = self.client.post(
                    reverse("resolve_invoice", args=[self.draft.pk]),
                    {
                        "customer_id": str(self.customer.pk),
                        "invoice_type": "B2B",
                        "item_sku_0": self.product.sku,
                        "item_qty_0": "5",
                    },
                )

                self.assertEqual(response.status_code, 302)

                self.draft.refresh_from_db()

                self.assertEqual(self.draft.status, "READY")
                self.assertEqual(self.draft.customer_id, self.customer.pk)
                self.assertEqual(self.draft.invoice_type, "B2B")
                self.assertEqual(
                    self.draft.total_amount,
                    Decimal("600.00"),
                )
                self.assertEqual(
                    self.draft.parsed_items_json[0]["sku"],
                    "SKU-101",
                )
                self.assertEqual(
                    self.draft.parsed_items_json[0]["match_method"],
                    "MANUAL_CONFIRMED",
                )

                self.assertTrue(
                    AuditLog.objects.filter(
                        invoice=self.draft,
                        action_description__contains="manually confirmed",
                    ).exists()
                )

            def test_resolution_rejects_invalid_quantity(self):
                response = self.client.post(
                    reverse("resolve_invoice", args=[self.draft.pk]),
                    {
                        "customer_id": str(self.customer.pk),
                        "invoice_type": "B2B",
                        "item_sku_0": self.product.sku,
                        "item_qty_0": "0",
                    },
                )

                self.assertEqual(response.status_code, 302)

                self.draft.refresh_from_db()

                self.assertEqual(self.draft.status, "ACTION_REQUIRED")
                self.assertIsNone(self.draft.customer_id)
                self.assertEqual(
                    self.draft.total_amount,
                    Decimal("0.00"),
                )

            def test_approved_draft_cannot_be_resolved(self):
                self.draft.status = "APPROVED"
                self.draft.save(update_fields=["status"])

                response = self.client.post(
                    reverse("resolve_invoice", args=[self.draft.pk]),
                    {
                        "customer_id": str(self.customer.pk),
                        "invoice_type": "B2B",
                        "item_sku_0": self.product.sku,
                        "item_qty_0": "5",
                    },
                )

                self.assertEqual(response.status_code, 302)

                self.draft.refresh_from_db()

                self.assertEqual(self.draft.status, "APPROVED")
                self.assertIsNone(self.draft.customer_id)

    @patch("invoicing.services.extract_order_with_llm")
    def test_llm_parser_uses_catalogue_price_not_model_price(self, mock_llm):
        mock_llm.return_value = {
            "items": [
                {
                    "description": "Please send two cartons of condensed milk",
                    "sku": "SKU-101",
                    "quantity": 2,
                    "confidence": 0.98,
                    "needs_confirmation": False,
                    # This extra value must be ignored.
                    "unit_price": 999999,
                }
            ]
        }

        parsed = parse_whatsapp_order(
            "Please send two cartons of condensed milk",
            self.customer,
        )

        self.assertEqual(parsed["parser"], "llm")
        self.assertEqual(parsed["items"][0]["sku"], "SKU-101")
        self.assertEqual(parsed["items"][0]["qty"], 2)
        self.assertEqual(
            parsed["items"][0]["unit_price"],
            "120.00",
        )
        self.assertEqual(parsed["total"], Decimal("240.00"))

    @patch("invoicing.services.extract_order_with_llm")
    def test_low_confidence_llm_match_requires_manual_confirmation(
            self,
            mock_llm,
    ):
        mock_llm.return_value = {
            "items": [
                {
                    "description": "some usual goods, five boxes",
                    "sku": "SKU-101",
                    "quantity": 5,
                    "confidence": 0.42,
                    "needs_confirmation": True,
                }
            ]
        }

        parsed = parse_whatsapp_order(
            "Boss, bagi barang biasa 5 kotak",
            self.customer,
        )

        item = parsed["items"][0]

        self.assertIsNone(item["sku"])
        self.assertEqual(item["match_status"], "UNMATCHED")
        self.assertEqual(parsed["total"], Decimal("0.00"))
        self.assertTrue(parsed["parse_errors"])

    @patch("invoicing.services.extract_order_with_llm")
    def test_llm_parser_uses_catalogue_price_not_model_price(self, mock_llm):
        mock_llm.return_value = {
            "items": [
                {
                    "description": "Please send two cartons of condensed milk",
                    "sku": "SKU-101",
                    "quantity": 2,
                    "confidence": 0.98,
                    "needs_confirmation": False,
                    # This extra value must be ignored.
                    "unit_price": 999999,
                }
            ]
        }

        parsed = parse_whatsapp_order(
            "Please send two cartons of condensed milk",
            self.customer,
        )

        self.assertEqual(parsed["parser"], "llm")
        self.assertEqual(parsed["items"][0]["sku"], "SKU-101")
        self.assertEqual(parsed["items"][0]["qty"], 2)
        self.assertEqual(
            parsed["items"][0]["unit_price"],
            "120.00",
        )
        self.assertEqual(parsed["total"], Decimal("240.00"))

    @patch("invoicing.services.extract_order_with_llm")
    def test_low_confidence_llm_match_requires_manual_confirmation(
            self,
            mock_llm,
    ):
        mock_llm.return_value = {
            "items": [
                {
                    "description": "some usual goods, five boxes",
                    "sku": "SKU-101",
                    "quantity": 5,
                    "confidence": 0.42,
                    "needs_confirmation": True,
                }
            ]
        }

        parsed = parse_whatsapp_order(
            "Boss, bagi barang biasa 5 kotak",
            self.customer,
        )

        item = parsed["items"][0]

        self.assertIsNone(item["sku"])
        self.assertEqual(item["match_status"], "UNMATCHED")
        self.assertEqual(parsed["total"], Decimal("0.00"))
        self.assertTrue(parsed["parse_errors"])

        def test_simulate_logs_parser_details(self):
            response = self.client.post(
                reverse("simulate_whatsapp"),
                {
                    "customer_id": self.customer.pk,
                    "message": "20 carton Susu Pekat",
                },
            )

            self.assertEqual(response.status_code, 302)

            draft = InvoiceDraft.objects.latest("id")

            parser_logs = AuditLog.objects.filter(
                invoice=draft,
                actor_role="SYSTEM / PARSER",
            )

            self.assertTrue(parser_logs.exists())

            log_text = " ".join(
                parser_logs.values_list(
                    "action_description",
                    flat=True,
                )
            )

            self.assertIn("Parser used: deterministic", log_text)
            self.assertIn("SKU-101", log_text)
            self.assertIn("confidence=1.00", log_text)

    def test_json_exports_only_approved_drafts(self):
        approved_draft = self.create_ready_draft()
        pending_draft = self.create_ready_draft()

        # Approve only the first draft.
        session = self.client.session
        session["orbyte_role"] = "OWNER"
        session.save()

        response = self.client.post(
            reverse(
                "approve_invoice",
                args=[approved_draft.pk],
            )
        )

        self.assertEqual(response.status_code, 302)

        # Download the accountant handover JSON.
        response = self.client.get(
            reverse("export_json")
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Content-Type"],
            "application/json",
        )
        self.assertIn(
            "JomInvois_Accountant_Handover.json",
            response["Content-Disposition"],
        )

        payload = response.json()

        self.assertEqual(payload["draft_count"], 1)
        self.assertEqual(len(payload["drafts"]), 1)

        exported = payload["drafts"][0]

        self.assertEqual(
            exported["draft_id"],
            approved_draft.pk,
        )
        self.assertEqual(
            exported["status"],
            "APPROVED",
        )
        self.assertEqual(
            exported["total_amount_rm"],
            "2400.00",
        )
        self.assertEqual(
            exported["customer"]["company_name"],
            self.customer.company_name,
        )
        self.assertTrue(exported["items"])
        self.assertTrue(exported["audit_trail"])

        self.assertNotEqual(
            exported["draft_id"],
            pending_draft.pk,
        )

        self.assertIn(
            "not an official LHDN/MyInvois",
            payload["disclaimer"],
        )
