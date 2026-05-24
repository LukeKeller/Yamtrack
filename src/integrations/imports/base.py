"""Base class shared by all per-source importers.

Owns the shared state (existing-media cache, deletion set, bulk-create buffer,
warning list) and the finalize step (cleanup + bulk-create + counts/warnings).
Subclasses implement ``import_data`` -- they call ``self.should_process`` to
gate each entry, push instances onto ``self.bulk_media[media_type]``, and
return ``self.finalize()``.
"""

import logging
from collections import defaultdict

from integrations.imports import helpers

logger = logging.getLogger(__name__)


class BaseImporter:
    """Common scaffolding for class-based importers.

    Subclasses set ``source_label`` and implement ``import_data``.
    """

    source_label: str = ""

    def __init__(self, user, mode):
        """Set up shared per-import state (called by each subclass ``__init__``)."""
        self.user = user
        self.mode = mode
        self.warnings: list[str] = []
        self.existing_media = helpers.get_existing_media(user)
        self.to_delete = defaultdict(lambda: defaultdict(set))
        self.bulk_media = defaultdict(list)
        logger.info(
            "Initialized %s importer for user %s with mode %s",
            self.source_label or self.__class__.__name__,
            user.username,
            mode,
        )

    def should_process(self, media_type, source, media_id):
        """Return whether this (type, source, id) should be processed.

        Implements mode dispatch: 'new' skips existing rows; 'overwrite' marks
        them for deletion before bulk-create runs.
        """
        return helpers.should_process_media(
            self.existing_media,
            self.to_delete,
            media_type,
            source,
            media_id,
            self.mode,
        )

    def finalize(self):
        """Clean up overwrites, bulk-create, return (counts, warnings)."""
        helpers.cleanup_existing_media(self.to_delete, self.user)
        helpers.bulk_create_media(self.bulk_media, self.user)
        counts = {
            media_type: len(media_list)
            for media_type, media_list in self.bulk_media.items()
        }
        deduplicated = "\n".join(dict.fromkeys(self.warnings))
        return counts, deduplicated

    def import_data(self):
        """Fetch entries, populate bulk_media, then return ``self.finalize()``."""
        raise NotImplementedError
