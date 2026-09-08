"""Compatibility exports for the migrated tag domain."""

from app.domain.tags.models import ProjectTag, ResourcePoolTag, TagDictionary, TagGroup, TaskTag

__all__ = ["ProjectTag", "ResourcePoolTag", "TagDictionary", "TagGroup", "TaskTag"]
