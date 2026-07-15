import unittest

from max_ftt_bot import trim_text


class TrimTextTests(unittest.TestCase):
    def test_keeps_short_text_unchanged(self):
        self.assertEqual(trim_text("Короткая новость."), "Короткая новость.")

    def test_ends_at_complete_sentence_before_target(self):
        first = "Первая законченная фраза. "
        text = first + "Следующая фраза продолжается заметно дольше лимита."

        self.assertEqual(trim_text(text, limit=35, hard_limit=70), first.strip())

    def test_extends_to_finish_sentence_after_target(self):
        text = "Одна цельная фраза немного выходит за целевую длину. Другая фраза."

        self.assertEqual(
            trim_text(text, limit=40, hard_limit=60),
            "Одна цельная фраза немного выходит за целевую длину.",
        )

    def test_long_sentence_is_cut_only_between_words(self):
        text = "Очень " + "длинное " * 30 + "предложение без точки"
        result = trim_text(text, limit=50, hard_limit=80)

        self.assertTrue(result.endswith("…"))
        self.assertLessEqual(len(result), 80)
        self.assertNotRegex(result[:-1], r"длинн$")


if __name__ == "__main__":
    unittest.main()
