"""Library upload forms.

The upload widget accepts an arbitrary number of files; the view does the
real work of demultiplexing (a .zip is walked for .epub members, a bare
.epub goes straight through, anything else is silently skipped). Keeping
the form thin lets us reuse the multi-file MultipleFileField pattern from
the Django docs without re-encoding ``files`` semantics here.
"""

from django import forms


class MultipleFileInput(forms.ClearableFileInput):
    """File widget that accepts more than one file per field."""

    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    """FileField variant that returns a list of UploadedFile, not just one."""

    def __init__(self, *args, **kwargs):
        """Default the widget to MultipleFileInput so the field accepts many."""
        kwargs.setdefault("widget", MultipleFileInput())
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        """Validate each upload individually so one bad file fails cleanly."""
        single_clean = super().clean
        if isinstance(data, list | tuple):
            return [single_clean(d, initial) for d in data]
        return [single_clean(data, initial)]


class LibraryUploadForm(forms.Form):
    """Upload one or more .epub / .zip files into the library."""

    files = MultipleFileField(
        label="EPUB or ZIP files",
        help_text=(
            "Pick one or more .epub files, or a .zip that contains them "
            "(subdirectories are walked). Non-epub files inside the zip are "
            "ignored."
        ),
    )
