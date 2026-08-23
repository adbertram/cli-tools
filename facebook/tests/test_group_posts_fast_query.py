import unittest

from facebook_cli.client import FacebookClient


class FakePage:
    def __init__(self):
        self.evaluate_calls = []
        self.waits = []
        self.extract_calls = 0

    def evaluate(self, script):
        self.evaluate_calls.append(script)
        if "window.scrollTo" in script:
            return None
        self.extract_calls += 1
        if self.extract_calls == 1:
            return [
                {
                    "post_id": "1001",
                    "author": "Ada",
                    "text": "First post",
                    "url": "https://www.facebook.com/groups/123/posts/1001/",
                    "reactions": 1,
                    "comment_count": 2,
                }
            ]
        return [
            {
                "post_id": "1001",
                "author": "Ada",
                "text": "First post",
                "url": "https://www.facebook.com/groups/123/posts/1001/",
                "reactions": 1,
                "comment_count": 2,
            },
            {
                "post_id": "1002",
                "author": "Grace",
                "text": "Second post",
                "url": "https://www.facebook.com/groups/123/posts/1002/",
                "reactions": 3,
                "comment_count": 4,
            },
        ]

    def wait_for_timeout(self, milliseconds):
        self.waits.append(milliseconds)


class GroupPostsDomQueryTests(unittest.TestCase):
    def test_extract_group_posts_extracts_posts_from_group_feed_dom(self):
        page = FakePage()
        client = FacebookClient()

        posts = client._extract_group_posts(page)

        self.assertEqual([post["post_id"] for post in posts], ["1001"])
        self.assertEqual(page.extract_calls, 1)
        self.assertEqual(page.waits, [])


if __name__ == "__main__":
    unittest.main()
