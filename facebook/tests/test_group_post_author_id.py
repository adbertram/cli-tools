"""A group post carries Facebook's own numeric poster id, not just a display name.

The node shapes below are verbatim from a live 2026-08-25 read of group
250458852075384 (`feedback.owning_profile`, `actors[0]`), with the session's own
tokens absent because a story node carries none.
"""
import unittest

from facebook_cli.client import FacebookClient
from facebook_cli.models import GroupPost


def _story_node(owning_profile):
    return {
        "post_id": "2557374301383816",
        "comet_sections": {
            "timestamp": {
                "story": {
                    "creation_time": 1787790851,
                    "url": "https://www.facebook.com/groups/250458852075384/posts/2557374301383816/",
                }
            },
            "content": {
                "story": {
                    "comet_sections": {
                        "message": {
                            "__typename": "CometFeedStoryDefaultMessageRenderingStrategy",
                            "story": {"message": {"text": "Selling a sealed 42182 - $175"}},
                        }
                    }
                }
            },
        },
        "feedback": {"owning_profile": owning_profile},
    }


class GroupPostAuthorIdTests(unittest.TestCase):
    def test_reads_owning_profile_id_alongside_name(self):
        node = _story_node({
            "__typename": "User",
            "name": "Kristian Walker",
            "short_name": "Kristian",
            "id": "100001077319362",
        })

        post = FacebookClient()._group_post_from_story_node("250458852075384", node)

        self.assertEqual(post["author"], "Kristian Walker")
        self.assertEqual(post["author_id"], "100001077319362")

    def test_author_id_is_none_when_facebook_names_no_owning_profile(self):
        """Absent is reported as absent. It is never derived from the name."""
        node = _story_node({"__typename": "User", "name": "Kristian Walker"})

        post = FacebookClient()._group_post_from_story_node("250458852075384", node)

        self.assertEqual(post["author"], "Kristian Walker")
        self.assertIsNone(post["author_id"])

    def test_author_id_is_a_group_post_field(self):
        post = GroupPost(post_id="2557374301383816", author="Kristian Walker",
                         author_id="100001077319362")

        self.assertEqual(post.model_dump()["author_id"], "100001077319362")


if __name__ == "__main__":
    unittest.main()
