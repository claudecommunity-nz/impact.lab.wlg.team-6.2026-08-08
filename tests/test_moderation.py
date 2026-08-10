"""The abuse filter must catch obvious profanity and obfuscation without
tripping on legitimate words that merely contain a flagged substring
(the Scunthorpe problem).
"""

from __future__ import annotations

import unittest

from kitea import moderation


class TestModeration(unittest.TestCase):
    def test_clean_text_passes(self):
        for ok in [
            "Water over the road on Hutt Rd, rising fast",
            "The class was cancelled; assess the situation at Scunthorpe.",
            "I can help dig — I have a spade and a 4WD.",
            "Massive slip near the assembly point.",
            "",
        ]:
            self.assertTrue(moderation.is_clean(ok), ok)

    def test_profanity_rejected(self):
        for bad in ["what the fuck", "this is shit", "you cunt",
                    "go kill yourself"]:
            self.assertFalse(moderation.is_clean(bad), bad)

    def test_leetspeak_and_repeats_rejected(self):
        for bad in ["fuuuuck this", "sh1t everywhere", "f4ggot", "b1tch"]:
            self.assertFalse(moderation.is_clean(bad), bad)

    def test_spaced_obfuscation_rejected(self):
        self.assertFalse(moderation.is_clean("f u c k this place"))

    def test_reason_is_user_safe(self):
        ok, reason = moderation.check("this is shit")
        self.assertFalse(ok)
        self.assertEqual(reason, "offensive language")


if __name__ == "__main__":
    unittest.main()
