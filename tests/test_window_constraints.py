import unittest


def validate_executed_vs_allowed(allowed_windows, executed_windows, progressive_windows_enabled=False):
    allowed = set(int(x) for x in allowed_windows)
    executed = [int(x) for x in executed_windows]
    if not progressive_windows_enabled:
        for w in executed:
            if w not in allowed:
                raise ValueError(f"executed window not allowed: {w}")
    return True


class TestWindowConstraints(unittest.TestCase):
    def test_allowed_4_8_executed_4_8_ok(self):
        self.assertTrue(validate_executed_vs_allowed([4, 8], [4, 8], progressive_windows_enabled=False))

    def test_allowed_4_8_executed_includes_24_fail(self):
        with self.assertRaises(ValueError):
            validate_executed_vs_allowed([4, 8], [4, 8, 24], progressive_windows_enabled=False)

    def test_allowed_4_executed_8_fail(self):
        with self.assertRaises(ValueError):
            validate_executed_vs_allowed([4], [8], progressive_windows_enabled=False)

    def test_progressive_enabled_allows_beyond_allowed_only_if_explicit(self):
        # In this minimal unit test, progressive enabled means we don't enforce strictness.
        self.assertTrue(validate_executed_vs_allowed([4, 8], [4, 8, 24], progressive_windows_enabled=True))


if __name__ == "__main__":
    unittest.main()

