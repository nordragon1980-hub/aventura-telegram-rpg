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
                "description": "Первый абзац.\n\nВторой абзац.",
                "threat": {"notes": "Нужны веревки и осторожность."},
            }
        )

        self.assertIn("<blockquote expandable>", text)
        self.assertIn("Сцена", text)
        self.assertIn("Первый абзац.", text)
        self.assertIn("Фокус: Нужны веревки и осторожность.", text)
        self.assertNotIn("<b>Сцена</b>", text)


if __name__ == "__main__":
    unittest.main()
