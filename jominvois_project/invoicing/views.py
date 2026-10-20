from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse
import csv
from .models import OrbyteCustomer, OrbyteProduct, InvoiceDraft, AuditLog
from .services import parse_whatsapp_order, validate_lhdn_readiness


def dashboard_view(request):
    # Set default role in session if not present
    if 'orbyte_role' not in request.session:
        request.session['orbyte_role'] = 'STAFF'

    current_role = request.session['orbyte_role']
    drafts = InvoiceDraft.objects.all().order_by('-created_at')
    customers = OrbyteCustomer.objects.all()

    context = {
        'current_role': current_role,
        'drafts': drafts,
        'customers': customers,
    }
    return render(request, 'invoicing/dashboard.html', context)


def switch_role_view(request):
    if request.method == 'POST':
        new_role = request.POST.get('role', 'STAFF')
        request.session['orbyte_role'] = new_role
    return redirect('dashboard')


def simulate_whatsapp_view(request):
    if request.method == 'POST':
        cust_id = request.POST.get('customer_id')
        message = request.POST.get('message')

        customer = OrbyteCustomer.objects.filter(id=cust_id).first()
        parsed_data = parse_whatsapp_order(message, customer)

        draft = InvoiceDraft.objects.create(
            customer=customer,
            raw_whatsapp_text=message,
            parsed_items_json=parsed_data['items'],
            invoice_type=parsed_data['invoice_type'],
            total_amount=parsed_data['total']
        )

        # Log trigger
        AuditLog.objects.create(
            invoice=draft,
            actor_role='SYSTEM (WhatsApp Bot)',
            action_description=f"Received order from {customer.company_name if customer else 'Unknown'}. Parsed {len(parsed_data['items'])} items."
        )

        # Run Rule Engine
        rule_logs = validate_lhdn_readiness(draft)
        for log in rule_logs:
            AuditLog.objects.create(
                invoice=draft,
                actor_role='SYSTEM (Rule Engine)',
                action_description=log
            )

    return redirect('dashboard')


def approve_invoice_view(request, draft_id):
    current_role = request.session.get('orbyte_role', 'STAFF')
    if current_role != 'OWNER':
        return HttpResponse("Unauthorized: Only the SME Owner can approve e-Invoice handover.", status=403)

    draft = get_object_or_404(InvoiceDraft, id=draft_id)
    draft.status = 'APPROVED'
    draft.save()

    AuditLog.objects.create(
        invoice=draft,
        actor_role='OWNER (Boss)',
        action_description=f"Approved Draft #{draft.id} for Accountant LHDN Handover Pack."
    )
    return redirect('dashboard')


def export_accountant_csv(request):
    """
    Generates the Accountant Summary Report CSV for LHDN MyInvois handover.
    """
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="Orbyte_JomInvois_Accountant_Handover.csv"'

    writer = csv.writer(response)
    writer.writerow(
        ['Draft ID', 'Invoice Type', 'Customer Name', 'Buyer TIN', 'Buyer BRN', 'Total Amount (RM)', 'Status',
         'Approved By Owner'])

    approved_drafts = InvoiceDraft.objects.filter(status='APPROVED')
    for d in approved_drafts:
        writer.writerow([
            d.id,
            d.invoice_type,
            d.customer.company_name if d.customer else 'Walk-in B2C',
            d.customer.tin_number if d.customer else 'N/A (Consolidated)',
            d.customer.brn_number if d.customer else 'N/A',
            d.total_amount,
            d.status,
            'Yes'
        ])
    return response