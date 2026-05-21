from cli_tools_shared.testing.auth_matrix import (
    AuthProfileSeed,
    seed_auth_profile,
    seed_auth_profiles,
)


def test_seed_auth_profile_writes_profile_env_and_browser_cookie(tmp_path):
    paths = seed_auth_profile(
        tmp_path,
        "default",
        is_default=True,
        env_body="CLIENT_ID=client\nACCESS_TOKEN=token\n",
        browser_session=True,
    )

    assert paths.profile_dir == tmp_path / "default"
    assert paths.env_file.read_text() == (
        "IS_DEFAULT_PROFILE=1\n"
        "CLIENT_ID=client\n"
        "ACCESS_TOKEN=token\n"
    )
    assert paths.cookies_file.exists()
    assert paths.cookies_file.read_text() == "sqlite-stub"


def test_seed_auth_profile_without_browser_session_leaves_cookie_absent(tmp_path):
    paths = seed_auth_profile(
        tmp_path,
        "oauth-only",
        is_default=False,
        env_body="CLIENT_ID=client\n",
        browser_session=False,
    )

    assert paths.env_file.read_text() == "IS_DEFAULT_PROFILE=0\nCLIENT_ID=client\n"
    assert not paths.cookies_file.exists()


def test_seed_auth_profiles_creates_named_matrix_in_order(tmp_path):
    paths = seed_auth_profiles(
        tmp_path,
        [
            AuthProfileSeed(
                name="oauth",
                is_default=True,
                env_body="ACCESS_TOKEN=token\n",
                browser_session=False,
            ),
            AuthProfileSeed(
                name="browser",
                is_default=False,
                env_body="",
                browser_session=True,
            ),
        ],
    )

    assert [item.profile_dir.name for item in paths] == ["oauth", "browser"]
    assert (tmp_path / "oauth" / ".env").read_text() == (
        "IS_DEFAULT_PROFILE=1\nACCESS_TOKEN=token\n"
    )
    assert not paths[0].cookies_file.exists()
    assert paths[1].cookies_file.exists()
