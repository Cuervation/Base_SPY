import unittest


def write_baseline_allowed(promoted_to_baseline: bool, apply_baseline_promotion_flag: bool) -> bool:
    return bool(promoted_to_baseline and apply_baseline_promotion_flag)


class TestBaselineImmutability(unittest.TestCase):
    def test_rejected_cannot_write(self):
        self.assertFalse(write_baseline_allowed(False, False))

    def test_followup_cannot_write(self):
        self.assertFalse(write_baseline_allowed(False, True))

    def test_promoted_without_flag_cannot_write(self):
        self.assertFalse(write_baseline_allowed(True, False))

    def test_promoted_with_flag_can_write(self):
        self.assertTrue(write_baseline_allowed(True, True))


if __name__ == "__main__":
    unittest.main()

