import unittest

from facebook_cli.main import _parse_fast_groups_posts_list


class GroupPostsLimitTests(unittest.TestCase):
    def test_fast_groups_posts_list_defaults_to_20(self):
        parsed = _parse_fast_groups_posts_list(["groups", "posts", "list", "123"])

        self.assertEqual(parsed[2], 20)

    def test_fast_groups_posts_list_accepts_limit_25(self):
        parsed = _parse_fast_groups_posts_list(
            ["groups", "posts", "list", "123", "--limit", "25", "--full-threads"]
        )

        self.assertEqual(parsed[2], 25)
        self.assertTrue(parsed[3])

    def test_fast_groups_posts_list_rejects_limits_over_25(self):
        parsed = _parse_fast_groups_posts_list(
            ["groups", "posts", "list", "123", "--limit", "26"]
        )

        self.assertIsNone(parsed)


if __name__ == "__main__":
    unittest.main()
