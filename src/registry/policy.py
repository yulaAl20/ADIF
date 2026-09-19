"""Information sections and field-level access (supervisor requirement 6).

ESPR Art. 10(1)(e) and Art. 9(2)(e) leave access rights to the delegated acts;
the CEN work item EN 18239 covers access control. The registry therefore makes access a
*configurable policy* rather than a hard-coded rule: every field belongs to a
named section, every section to a tier, and every response is filtered by the
caller's role before it leaves the registry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import yaml

__all__ = ["Role", "Principal", "AccessPolicy", "PUBLIC"]

TIER_ORDER = {"public": 0, "registrant": 1, "authority": 2}


class Role(str, Enum):
    PUBLIC = "public"
    REGISTRANT = "registrant"
    AUTHORITY = "authority"
    OPERATOR = "operator"


@dataclass(frozen=True)
class Principal:
    """Who is asking. ``registrar_id`` is set for registrants."""

    role: Role
    registrar_id: str | None = None

    def can_read_tier(self, tier: str, owner: str) -> bool:
        if self.role in (Role.AUTHORITY, Role.OPERATOR):
            return True
        if tier == "public":
            return True
        if tier == "registrant":
            return self.role == Role.REGISTRANT and self.registrar_id == owner
        return False

    def owns(self, owner: str) -> bool:
        return self.role == Role.OPERATOR or (
            self.role == Role.REGISTRANT and self.registrar_id == owner
        )

    @property
    def privileged(self) -> bool:
        return self.role in (Role.AUTHORITY, Role.OPERATOR)


PUBLIC = Principal(Role.PUBLIC)


@dataclass
class AccessPolicy:
    sections: dict[str, dict[str, Any]] = field(default_factory=dict)
    public_kinds: tuple[str, ...] = ("model", "variant")
    max_page_size: int = 50

    def __post_init__(self) -> None:
        self._field_section: dict[str, str] = {}
        for name, spec in self.sections.items():
            for f in spec.get("fields", []):
                self._field_section[f] = name

    @classmethod
    def load(cls, path: str | Path = "config/registry.yaml") -> AccessPolicy:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        search = raw.get("search", {})
        return cls(
            sections=raw.get("sections", {}),
            public_kinds=tuple(search.get("public_kinds", ["model", "variant"])),
            max_page_size=int(search.get("max_page_size", 50)),
        )

    def section_of(self, field_name: str) -> str:
        return self._field_section.get(field_name, "other")

    def tier_of_section(self, section: str) -> str:
        if section == "other":
            return "registrant"
        return self.sections.get(section, {}).get("tier", "registrant")

    def tier_of(self, field_name: str) -> str:
        return self.tier_of_section(self.section_of(field_name))

    def is_public(self, field_name: str) -> bool:
        return self.tier_of(field_name) == "public"

    def sectioned(
        self, metadata: dict[str, Any], principal: Principal, owner: str
    ) -> tuple[dict[str, dict[str, Any]], list[str]]:
        """Split metadata into sections the principal may read.

        Returns:
            ``(sections, withheld)`` — withheld lists *section names* that exist
            but were not shown, so a reader knows information exists without
            seeing it.
        """
        visible: dict[str, dict[str, Any]] = {}
        withheld: set[str] = set()
        for key, value in metadata.items():
            section = self.section_of(key)
            if principal.can_read_tier(self.tier_of_section(section), owner):
                visible.setdefault(section, {})[key] = value
            else:
                withheld.add(section)
        return visible, sorted(withheld)

    def filter_flat(
        self, metadata: dict[str, Any], principal: Principal, owner: str
    ) -> dict[str, Any]:
        return {
            k: v for k, v in metadata.items()
            if principal.can_read_tier(self.tier_of(k), owner)
        }
