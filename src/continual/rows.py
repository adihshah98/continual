"""Shared base for typed DB-row models returned to the API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class RowModel(BaseModel):
    """Base for a DB-query result row. Subclass with the columns you SELECT."""

    # An extra selected column shouldn't 500; declared columns stay validated.
    model_config = ConfigDict(extra="ignore")

    def as_json(self) -> dict[str, Any]:
        """JSON-safe dict: UUID -> str, datetime -> ISO 8601, etc."""
        return self.model_dump(mode="json")

    @classmethod
    def rows_to_json(cls, rows: list[dict]) -> list[dict]:
        """Validate + JSON-serialize a list of psycopg dict_row results."""
        return [cls(**row).as_json() for row in rows]

    @classmethod
    def row_to_json(cls, row: dict) -> dict:
        """Validate + JSON-serialize a single psycopg dict_row result."""
        return cls(**row).as_json()
