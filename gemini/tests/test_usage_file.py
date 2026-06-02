from gemini_cli.usage import get_usage_file


def test_usage_file_is_visible_json_in_profile_data_dir(tmp_path):
    class _Config:
        def get_profile_data_dir(self):
            return tmp_path / "profile"

    assert get_usage_file(_Config()) == tmp_path / "profile" / "usage.json"
