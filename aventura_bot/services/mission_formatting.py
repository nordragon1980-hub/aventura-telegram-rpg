from __future__ import annotations

import html
from typing import Any


def format_expandable_mission_details(mission: dict[str, Any]) -> str:
    detail_lines = ["Сцена"]
    description = str(mission.get("description") or "").strip()
    if description:
        for paragraph in description.split("\n\n"):
            cleaned = paragraph.strip()
            if not cleaned:
                continue
            if len(detail_lines) > 1:
                detail_lines.append("")
            detail_lines.append(cleaned)

    threat = mission.get("threat") or {}
    if not isinstance(threat, dict):
        threat = {}
    notes = str(threat.get("notes") or "").strip()
    if notes:
        if len(detail_lines) > 1:
            detail_lines.append("")
        detail_lines.append(f"Фокус: {notes}")

    if len(detail_lines) == 1:
        return ""
    details = html.escape("\n".join(detail_lines))
    return f"<blockquote expandable>{details}</blockquote>"
