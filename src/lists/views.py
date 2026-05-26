import logging

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count, F, OuterRef, Q, Subquery
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from app import helpers
from app.helpers import extract_release_date
from app.models import Item, MediaManager, MediaTypes
from app.providers import services
from app.providers.services import ProviderAPIError
from lists.forms import CustomListForm, ListImportForm
from lists.models import CustomList, CustomListItem
from users.models import ListDetailSortChoices, ListSortChoices, MediaStatusChoices

logger = logging.getLogger(__name__)

UNMATCHED_PREVIEW_LIMIT = 5


@require_GET
def lists(request):
    """Return the custom list page."""
    # Get parameters from request
    search_query = request.GET.get("q", "")
    page = request.GET.get("page", 1)
    sort_by = request.user.update_preference("lists_sort", request.GET.get("sort"))

    custom_lists = CustomList.objects.get_user_lists(request.user)

    if search_query:
        custom_lists = custom_lists.filter(
            Q(name__icontains=search_query) | Q(description__icontains=search_query),
        )

    if sort_by == "name":
        custom_lists = custom_lists.order_by("name")
    elif sort_by == "items_count":
        custom_lists = custom_lists.annotate(
            items_count=Count("items", distinct=True),
        ).order_by("-items_count")
    elif sort_by == "newest_first":
        custom_lists = custom_lists.order_by("-id")
    else:  # last_item_added is the default
        # Get the latest update date for each list
        custom_lists = custom_lists.annotate(
            latest_update=Subquery(
                CustomListItem.objects.filter(
                    custom_list=OuterRef("pk"),
                )
                .order_by("-date_added")
                .values("date_added")[:1],
            ),
        ).order_by("-latest_update", "name")

    items_per_page = 20
    paginator = Paginator(custom_lists, items_per_page)
    lists_page = paginator.get_page(page)

    # Create a form for each list
    # needs unique id for django-select2
    for i, custom_list in enumerate(lists_page, start=1):
        custom_list.form = CustomListForm(
            instance=custom_list,
            auto_id=f"id_{i}_%s",
        )

    if request.headers.get("HX-Request"):
        return render(
            request,
            "lists/components/list_grid.html",
            {
                "custom_lists": lists_page,
            },
        )

    create_list_form = CustomListForm()

    return render(
        request,
        "lists/custom_lists.html",
        {
            "custom_lists": lists_page,
            "form": create_list_form,
            "current_sort": sort_by,
            "sort_choices": ListSortChoices.choices,
        },
    )


@require_GET
def list_detail(request, list_id):
    """Return the detail page of a custom list."""
    custom_list = get_object_or_404(
        CustomList.objects.select_related("owner").prefetch_related("collaborators"),
        id=list_id,
    )

    if not custom_list.user_can_view(request.user):
        msg = "List not found"
        raise Http404(msg)

    # Get and process request parameters
    params = {
        "sort_by": request.user.update_preference(
            "list_detail_sort",
            request.GET.get("sort"),
        ),
        "media_type": request.GET.get("type", "all"),
        "status_filter": request.user.update_preference(
            "list_detail_status",
            request.GET.get("status"),
        ),
        "page": int(request.GET.get("page", 1)),
        "search_query": request.GET.get("q", ""),
    }

    # Build and filter base queryset
    items = custom_list.items.all()
    if params["search_query"]:
        items = items.filter(title__icontains=params["search_query"])
    if params["media_type"] != "all":
        items = items.filter(media_type=params["media_type"])

    # Get distinct media types for filtering
    media_types = items.values_list("media_type", flat=True).distinct()
    media_manager = MediaManager()
    media_by_item_id = {}

    # Filter by status if specified
    if params["status_filter"] != MediaStatusChoices.ALL:
        item_ids = items.values_list("id", flat=True)
        media_by_item_id = media_manager.fetch_media_for_items(
            media_types,
            item_ids,
            request.user,
            status_filter=params["status_filter"],
        )
        # Filter items to only those with the specified status
        items = items.filter(id__in=media_by_item_id.keys())

    # Apply sorting
    sort_mapping = {
        "date_added": ["-customlistitem__date_added"],
        "title": [
            F("title").asc(nulls_last=True),
            F("season_number").asc(nulls_first=True),
            F("episode_number").asc(nulls_first=True),
        ],
        "media_type": ["media_type"],
        "release_date": [
            F("air_date").asc(nulls_last=True),
            F("title").asc(nulls_last=True),
        ],
    }
    items = items.order_by(
        *sort_mapping.get(params["sort_by"], ["-customlistitem__date_added"]),
    )

    # Paginate
    paginator = Paginator(items, 16)
    items_page = paginator.get_page(params["page"])

    # If no status filter was applied, fetch media objects for paginated items only
    if params["status_filter"] == MediaStatusChoices.ALL:
        media_types_in_page = {item.media_type for item in items_page}
        page_item_ids = [item.id for item in items_page]
        media_by_item_id = media_manager.fetch_media_for_items(
            media_types_in_page,
            page_item_ids,
            request.user,
        )

    # Annotate items with media objects
    for item in items_page:
        item.media = media_by_item_id.get(item.id)

    # Base context for both full and partial responses
    context = {
        "custom_list": custom_list,
        "items": items_page,
        "has_next": items_page.has_next(),
        "next_page_number": items_page.next_page_number()
        if items_page.has_next()
        else None,
        "current_sort": params["sort_by"],
        "current_status": params["status_filter"] or MediaStatusChoices.ALL,
        "sort_choices": ListDetailSortChoices.choices,
        "status_choices": MediaStatusChoices.choices,
    }

    # Additional context for full page render
    if not request.headers.get("HX-Request"):
        context.update(
            {
                "form": CustomListForm(instance=custom_list),
                "media_types": MediaTypes.values,
                "items_count": paginator.count,
                "collaborators_count": custom_list.collaborators.count() + 1,
            },
        )
        return render(request, "lists/list_detail.html", context)

    # HTMX partial response
    return render(request, "lists/components/media_grid.html", context)


@require_POST
def create(request):
    """Create a new custom list."""
    form = CustomListForm(request.POST)
    if form.is_valid():
        custom_list = form.save(commit=False)
        custom_list.owner = request.user
        custom_list.save()
        form.save_m2m()
        logger.info("%s list created successfully.", custom_list)
    else:
        logger.error(form.errors.as_json())
        helpers.form_error_messages(form, request)
    return helpers.redirect_back(request)


@require_POST
def edit(request):
    """Edit an existing custom list."""
    list_id = request.POST.get("list_id")
    custom_list = get_object_or_404(CustomList, id=list_id)
    if custom_list.user_can_edit(request.user):
        form = CustomListForm(request.POST, instance=custom_list)
        if form.is_valid():
            form.save()
            logger.info("%s list edited successfully.", custom_list)
    else:
        messages.error(request, "You do not have permission to edit this list.")
    return helpers.redirect_back(request)


@require_POST
def delete(request):
    """Delete a custom list."""
    list_id = request.POST.get("list_id")
    custom_list = get_object_or_404(CustomList, id=list_id)
    if custom_list.user_can_delete(request.user):
        custom_list.delete()
        logger.info("%s list deleted successfully.", custom_list)
        return redirect("lists")

    messages.error(request, "You do not have permission to delete this list.")
    return helpers.redirect_back(request)


@require_GET
def lists_modal(
    request,
    source,
    media_type,
    media_id,
    season_number=None,
    episode_number=None,
):
    """Return the modal showing all custom lists and allowing to add to them."""
    try:
        item = Item.objects.get(
            media_id=media_id,
            source=source,
            media_type=media_type,
            season_number=season_number,
            episode_number=episode_number,
        )
    except Item.DoesNotExist:
        metadata = services.get_media_metadata(
            media_type,
            media_id,
            source,
            [season_number],
            episode_number,
        )
        item = Item.objects.create(
            media_id=media_id,
            source=source,
            media_type=media_type,
            season_number=season_number,
            episode_number=episode_number,
            title=metadata["title"],
            image=metadata["image"],
            air_date=extract_release_date(metadata),
        )

    custom_lists = CustomList.objects.get_user_lists_with_item(request.user, item)

    return render(
        request,
        "lists/components/fill_lists.html",
        {"item": item, "custom_lists": custom_lists},
    )


def _resolve_or_create_item(search_hit):
    """Return the Item described by a search-result dict, creating if needed.

    Tries to populate ``air_date`` from a metadata fetch so the new
    "Release Date" sort works immediately for freshly-imported items.
    Failures are logged and treated as missing data — never fatal.
    """
    media_id = str(search_hit["media_id"])
    source = search_hit["source"]
    media_type = search_hit["media_type"]
    item = Item.objects.filter(
        media_id=media_id,
        source=source,
        media_type=media_type,
        season_number=None,
        episode_number=None,
    ).first()
    if item is not None:
        return item

    air_date = None
    try:
        metadata = services.get_media_metadata(media_type, media_id, source)
        air_date = extract_release_date(metadata)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "List import: metadata fetch failed for %s/%s/%s: %s",
            media_type,
            source,
            media_id,
            exc,
        )

    return Item.objects.create(
        media_id=media_id,
        source=source,
        media_type=media_type,
        title=search_hit["title"],
        image=search_hit["image"],
        air_date=air_date,
    )


@require_GET
def list_import_form(request):
    """Render the empty list-import form."""
    return render(request, "lists/import_list.html", {"form": ListImportForm()})


@require_POST
def list_import(request):
    """Bulk-create a new CustomList from a pasted list of titles."""
    form = ListImportForm(request.POST)
    if not form.is_valid():
        return render(request, "lists/import_list.html", {"form": form})

    titles = form.cleaned_data["titles"]
    media_type = form.cleaned_data["media_type"]

    custom_list = CustomList.objects.create(
        name=form.cleaned_data["name"],
        description=form.cleaned_data["description"],
        owner=request.user,
    )

    matched_count = 0
    unmatched = []
    for title in titles:
        try:
            results = services.search(media_type, title, page=1)
        except ProviderAPIError as exc:
            logger.warning("List import: search failed for %r: %s", title, exc)
            unmatched.append(title)
            continue

        hits = results.get("results") or []
        if not hits:
            unmatched.append(title)
            continue

        item = _resolve_or_create_item(hits[0])
        _, created = CustomListItem.objects.get_or_create(
            item=item,
            custom_list=custom_list,
        )
        if created:
            matched_count += 1

    if matched_count == 0:
        # Don't leave behind an empty list — re-render the form with
        # the user's inputs so they can adjust the media type or fix typos.
        custom_list.delete()
        messages.error(
            request,
            "Nothing matched any of those titles — list not created.",
        )
        return render(request, "lists/import_list.html", {"form": form})

    messages.success(
        request,
        f"Added {matched_count} item(s) to {custom_list.name!r}.",
    )
    if unmatched:
        preview = ", ".join(unmatched[:UNMATCHED_PREVIEW_LIMIT])
        overflow = len(unmatched) - UNMATCHED_PREVIEW_LIMIT
        if overflow > 0:
            preview += f" and {overflow} more"
        messages.warning(request, f"Could not match: {preview}")

    return redirect("list_detail", list_id=custom_list.id)


@require_POST
def list_item_toggle(request):
    """Add or remove an item from a custom list."""
    item_id = request.POST["item_id"]
    custom_list_id = request.POST["custom_list_id"]

    item = get_object_or_404(Item, id=item_id)
    custom_list = get_object_or_404(
        CustomList.objects.filter(
            Q(owner=request.user) | Q(collaborators=request.user),
            id=custom_list_id,
        ).distinct(),  # To prevent duplicates, when user is owner and collaborator
    )

    if custom_list.items.filter(id=item.id).exists():
        custom_list.items.remove(item)
        logger.info("%s removed from %s.", item, custom_list)
        has_item = False
    else:
        custom_list.items.add(item)
        logger.info("%s added to %s.", item, custom_list)
        has_item = True

    return render(
        request,
        "lists/components/list_item_button.html",
        {"custom_list": custom_list, "item": item, "has_item": has_item},
    )
