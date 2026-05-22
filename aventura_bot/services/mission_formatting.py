from __future__ import annotations

import html
from typing import Any


def format_expandable_mission_details(mission: dict[str, Any]) -> str:
    detail_lines: list[str] = []
    description = str(mission.get("description") or "").strip()
    if description:
        for paragraph in description.split("\n\n"):
            cleaned = paragraph.strip()
            if not cleaned:
                continue
            if detail_lines:
                detail_lines.append("")
            detail_lines.append(cleaned)

    if not detail_lines:
        return ""
    details = html.escape("\n".join(detail_lines))
    return f"<blockquote expandable>{details}</blockquote>"
