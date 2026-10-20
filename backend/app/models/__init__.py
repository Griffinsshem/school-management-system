"""Database models. Importing them here registers them for migrations."""

from app.models.user import User

__all__ = ["User"]
