"""
Quick Sell Views — Phase 5

Views for Quick Sell listing management.
Reuses the EXISTING Vendor Product taxonomy (MainCategory -> SubCategory -> SubCategoryAttribute).

DO NOT create QuickSellCategory, QuickSellSubCategory, or QuickSellAttribute.
The existing Vendor taxonomy is the SINGLE SOURCE OF TRUTH.
"""

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, Http404
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.utils import timezone

from apps.vendors.models import MainCategory, SubCategory, SubCategoryAttribute
from apps.quicksell.models import QuickSell, QuickSellImage, QuickSellReport
from apps.quicksell.forms import (
    QuickSellCreateForm,
    QuickSellEditForm,
    QuickSellImageFormSet,
)


# ==========================================
# QUICK SELL VIEWS
# ==========================================

def quick_sell_landing(request):
    """Redirect to create or my listings based on auth."""
    if request.user.is_authenticated:
        return redirect('quicksell:my_listings')
    return redirect('marketplace:product_list')


@login_required
def quick_sell_create(request):
    """
    Create a new Quick Sell listing.
    Reuses the EXISTING Vendor Product taxonomy.
    """
    if request.method == 'POST':
        form = QuickSellCreateForm(
            request.POST,
            request.FILES,
            user=request.user
        )
        image_formset = QuickSellImageFormSet(
            request.POST,
            request.FILES,
            prefix='images'
        )

        if form.is_valid() and image_formset.is_valid():
            listing = form.save()

            # Save image formset with the listing instance
            image_formset.instance = listing
            image_formset.save()

            messages.success(request, 'Your listing has been created!')
            return redirect('quicksell:detail', slug=listing.slug)
    else:
        form = QuickSellCreateForm(user=request.user)
        image_formset = QuickSellImageFormSet(prefix='images')

    context = {
        'form': form,
        'image_formset': image_formset,
        'request': request,
    }
    return render(request, 'quicksell/create.html', context)


def quick_sell_detail(request, slug):
    """Public Quick Sell listing detail. Expired listings return 404 for public users."""
    listing = get_object_or_404(QuickSell, slug=slug)

    # Expired listings are not publicly accessible
    if not listing.is_active:
        # Owner can still see their expired listing
        if request.user.is_authenticated and request.user == listing.user:
            return render(request, 'quicksell/detail.html', {
                'listing': listing,
                'is_owner': True,
            })
        raise Http404("This listing has expired.")

    return render(request, 'quicksell/detail.html', {
        'listing': listing,
        'is_owner': request.user.is_authenticated and request.user == listing.user,
    })


@login_required
def quick_sell_edit(request, slug):
    """
    Edit a Quick Sell listing.
    Ownership enforced server-side.
    """
    listing = get_object_or_404(QuickSell, slug=slug, user=request.user)

    if request.method == 'POST':
        form = QuickSellEditForm(
            request.POST,
            request.FILES,
            instance=listing,
            user=request.user
        )
        image_formset = QuickSellImageFormSet(
            request.POST,
            request.FILES,
            instance=listing,
            prefix='images'
        )

        if form.is_valid() and image_formset.is_valid():
            form.save()
            image_formset.save()

            messages.success(request, 'Your listing has been updated!')
            return redirect('quicksell:detail', slug=listing.slug)
    else:
        form = QuickSellEditForm(instance=listing, user=request.user)
        image_formset = QuickSellImageFormSet(instance=listing, prefix='images')

    import json
    context = {
        'form': form,
        'image_formset': image_formset,
        'listing': listing,
        'existing_attributes_json': json.dumps(listing.attributes or {}),
    }
    return render(request, 'quicksell/edit.html', context)


@login_required
def quick_sell_delete(request, slug):
    """Delete own Quick Sell listing. POST only — no delete page."""
    if request.method != 'POST':
        return redirect('quicksell:my_listings')

    listing = get_object_or_404(QuickSell, slug=slug, user=request.user)
    listing.delete()
    messages.success(request, 'Your listing has been deleted.')
    return redirect('quicksell:my_listings')


@login_required
def quick_sell_my_listings(request):
    """User's own Quick Sell listings with status filtering."""
    status_filter = request.GET.get('status', 'all')
    listings = QuickSell.objects.filter(user=request.user).order_by('-created_at')

    if status_filter == 'active':
        listings = listings.active()
    elif status_filter == 'expired':
        listings = listings.expired()

    context = {
        'listings': listings,
        'current_filter': status_filter,
    }
    return render(request, 'quicksell/my_listings.html', context)


# ==========================================
# AJAX ENDPOINTS
# ==========================================

@login_required
def ajax_quick_sell_subcategories(request):
    """
    AJAX endpoint to get subcategories for a given MainCategory.
    Reuses the EXISTING Vendor Product taxonomy.
    """
    main_category_id = request.GET.get('main_category_id')

    if not main_category_id:
        return JsonResponse({'subcategories': []})

    subcategories = SubCategory.objects.filter(
        main_category_id=main_category_id,
        is_active=True
    ).values('id', 'name').order_by('name')

    return JsonResponse({
        'subcategories': list(subcategories)
    })


@login_required
def ajax_quick_sell_attributes(request):
    """
    AJAX endpoint to get attributes for a specific subcategory.
    Reuses the SAME SubCategoryAttribute records used by Vendor Products.
    """
    subcategory_id = request.GET.get('subcategory_id')

    if not subcategory_id:
        return JsonResponse({'attributes': []})

    attributes = SubCategoryAttribute.objects.filter(
        subcategory_id=subcategory_id,
        is_active=True
    ).order_by('sort_order')

    attrs_data = []
    for attr in attributes:
        attrs_data.append({
            'id': attr.id,
            'name': attr.name,
            'field_type': attr.field_type,
            'is_required': attr.is_required,
            'placeholder': attr.placeholder,
            'help_text': attr.help_text,
            'options': attr.options if attr.field_type == 'dropdown' else []
        })

    return JsonResponse({'attributes': attrs_data})


# ==========================================
# REPORTING
# ==========================================

@login_required
def report_quick_sell(request, id):
    """Report a quick sell listing. POST only."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    listing = get_object_or_404(QuickSell, id=id)

    # Cannot report own listing
    if request.user == listing.user:
        return JsonResponse({'error': 'You cannot report your own listing'}, status=400)

    reason = request.POST.get('reason', '').strip()
    details = request.POST.get('details', '').strip()

    if not reason:
        return JsonResponse({'error': 'Please select a reason'}, status=400)

    valid_reasons = [c[0] for c in QuickSellReport.REASON_CHOICES]
    if reason not in valid_reasons:
        return JsonResponse({'error': 'Invalid reason'}, status=400)

    QuickSellReport.objects.create(
        reporter=request.user,
        reporter_ip=request.META.get('REMOTE_ADDR'),
        quicksell=listing,
        reason=reason,
        details=details,
    )

    return JsonResponse({'success': True, 'message': 'Report submitted. Thank you for helping keep our marketplace safe.'})
