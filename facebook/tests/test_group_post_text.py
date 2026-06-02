import unittest

from facebook_cli.client import FacebookClient


class GroupPostTextTests(unittest.TestCase):
    def test_extracts_formatted_background_story_message_text(self):
        node = {
            "comet_sections": {
                "content": {
                    "story": {
                        "comet_sections": {
                            "message": {
                                "__typename": "CometFeedStoryFormattedBackgroundMessageRenderingStrategy",
                                "story": {
                                    "message": {
                                        "text": "What is this set worth?",
                                    },
                                    "text_format_metadata": {
                                        "background_color": "FFE2013B",
                                        "color": "FFFFFFFF",
                                    },
                                },
                            },
                        },
                    },
                },
            },
        }

        self.assertEqual(
            FacebookClient()._extract_group_post_text(node),
            "What is this set worth?",
        )


if __name__ == "__main__":
    unittest.main()
