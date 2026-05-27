from django.contrib import admin

from library.models import LibraryFile


@admin.register(LibraryFile)
class LibraryFileAdmin(admin.ModelAdmin):
    """Admin for the library — handy on staging when files don't auto-bind."""

    list_display = (
        "canonical_filename",
        "user",
        "title",
        "author",
        "item",
        "size_bytes",
        "created_at",
    )
    list_filter = ("user", "language")
    search_fields = ("canonical_filename", "title", "author", "isbn_13")
    readonly_fields = ("koreader_filename_md5", "created_at", "updated_at")
