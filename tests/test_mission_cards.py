import unittest

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


if __name__ == "__main__":
    unittest.main()
