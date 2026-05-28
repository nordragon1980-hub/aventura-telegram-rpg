import unittest

from aventura_bot.bot import _format_mission_card
from aventura_bot.services.mission_formatting import format_expandable_mission_details


class MissionCardFormatTests(unittest.TestCase):
    def test_mission_description_uses_expandable_blockquote(self):
        text = format_expandable_mission_details(
            {
                "id": 7,
                "title": "Черный Водоподъемник",
                "mission_type": "standard",
                "difficulty": 9,
                "description": "Художественное описание\n\nПервый абзац.\n\nЦели миссии\n\n1. Обезвредить банду.",
                "threat": {"notes": "Нужны веревки и осторожность."},
            }
        )

        self.assertIn("<blockquote expandable>", text)
        self.assertIn("Первый абзац.", text)
        self.assertIn("Цели миссии", text)
        self.assertIn("1. Обезвредить банду.", text)
        self.assertNotIn("Сцена", text)
        self.assertNotIn("Фокус", text)
        self.assertNotIn("Нужны веревки", text)
        self.assertNotIn("<b>Сцена</b>", text)

    def test_boss_mission_card_has_boss_marker(self):
        text = _format_mission_card(
            {
                "id": 9,
                "title": "Сердце Черного Водоподъемника",
                "mission_type": "boss",
                "mission_subtype": "phased",
                "phase": 2,
                "max_phase": 3,
                "max_participants": 5,
                "difficulty": 14,
                "description": "Художественное описание\n\nЦели миссии\n\n1. Сорвать ритуал.",
            }
        )

        self.assertIn("<b>!!! БОСС !!!</b>", text)
        self.assertIn("<b>Тип:</b> босс-миссия", text)
        self.assertIn("<b>Фаза:</b> 2/3", text)
        self.assertIn("<b>Опасность:</b>", text)
        self.assertNotIn("Сложность:", text)
        self.assertNotIn(">14<", text)


if __name__ == "__main__":
    unittest.main()
