from django import forms
from django_select2 import forms as s2forms

from app.models import MediaTypes
from lists.models import CustomList

MAX_IMPORT_TITLES = 100

# Season and episode entries are tied to a parent show and aren't a
# coherent first-class thing to bulk-search for from a list paste.
_BULK_IMPORTABLE_TYPES = [
    mt
    for mt in MediaTypes.values
    if mt not in {MediaTypes.SEASON.value, MediaTypes.EPISODE.value}
]


class CollaboratorsWidget(s2forms.ModelSelect2MultipleWidget):
    """Custom widget for selecting multiple users."""

    search_fields = ["username__icontains"]


class CustomListForm(forms.ModelForm):
    """Form for creating new custom lists."""

    class Meta:
        """Bind form to model."""

        model = CustomList
        fields = ["name", "description", "collaborators"]
        widgets = {
            "collaborators": CollaboratorsWidget(
                attrs={
                    "data-minimum-input-length": 1,
                    "data-placeholder": "Search users to add...",
                    "data-allow-clear": "false",
                },
            ),
        }


class ListImportForm(forms.Form):
    """Form for creating a CustomList from a pasted list of titles."""

    name = forms.CharField(max_length=255, label="List name")
    description = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
    )
    media_type = forms.ChoiceField(
        choices=[(mt, mt.replace("_", " ").title()) for mt in _BULK_IMPORTABLE_TYPES],
        label="Media type",
        help_text="All pasted titles are searched against this media type.",
    )
    titles = forms.CharField(
        widget=forms.Textarea(
            attrs={
                "rows": 12,
                "placeholder": (
                    "One title per line.\nThe top search result is added "
                    "to the new list."
                ),
            },
        ),
        help_text=f"At most {MAX_IMPORT_TITLES} titles per import.",
    )

    def clean_titles(self):
        """Strip blank lines and enforce the row cap."""
        raw = self.cleaned_data["titles"]
        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        if not lines:
            msg = "Paste at least one title."
            raise forms.ValidationError(msg)
        if len(lines) > MAX_IMPORT_TITLES:
            msg = (
                f"At most {MAX_IMPORT_TITLES} titles per import "
                f"(you pasted {len(lines)})."
            )
            raise forms.ValidationError(msg)
        return lines
