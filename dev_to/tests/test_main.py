from pathlib import Path

from typer.testing import CliRunner

from dev_to_cli.main import app


runner = CliRunner()


class FakeClient:
    def create_post(self, **kwargs):
        self.kwargs = kwargs
        return {
            "id": 42,
            "title": kwargs["title"],
            "published": kwargs["published"],
            "tag_list": ["python"],
            "url": "https://dev.to/example-user/post",
            "published_at": None,
        }

    def remove_post(self, post_id):
        self.post_id = post_id
        return {
            "id": post_id,
            "title": "Draft",
            "published": False,
            "url": "https://dev.to/example-user/draft",
        }


def test_posts_create_requires_one_body_source(tmp_path):
    result = runner.invoke(
        app,
        [
            "posts",
            "create",
            "--title",
            "Hello DEV",
        ],
    )

    assert result.exit_code == 1
    assert "Provide exactly one of --body-markdown or --body-file." in result.stderr


def test_posts_create_rejects_multiple_body_sources(tmp_path):
    body_file = tmp_path / "post.md"
    body_file.write_text("# Hello\n")

    result = runner.invoke(
        app,
        [
            "posts",
            "create",
            "--title",
            "Hello DEV",
            "--body-markdown",
            "# Inline",
            "--body-file",
            str(body_file),
        ],
    )

    assert result.exit_code == 1
    assert "Provide exactly one of --body-markdown or --body-file." in result.stderr


def test_posts_create_reads_body_file_and_passes_supported_fields(monkeypatch, tmp_path):
    body_file = tmp_path / "post.md"
    body_file.write_text("# Hello\n")
    fake_client = FakeClient()
    monkeypatch.setattr("dev_to_cli.main.get_client", lambda: fake_client)

    result = runner.invoke(
        app,
        [
            "posts",
            "create",
            "--title",
            "Hello DEV",
            "--body-file",
            str(body_file),
            "--published",
            "--tags",
            "python",
            "--canonical-url",
            "https://example.com/post",
            "--description",
            "Short description",
            "--series",
            "CLI Series",
            "--main-image",
            "https://example.com/image.png",
        ],
    )

    assert result.exit_code == 0
    assert fake_client.kwargs == {
        "title": "Hello DEV",
        "body_markdown": "# Hello\n",
        "published": True,
        "tags": "python",
        "canonical_url": "https://example.com/post",
        "description": "Short description",
        "series": "CLI Series",
        "main_image": "https://example.com/image.png",
    }
    assert '"id": 42' in result.stdout


def test_posts_unpublish_calls_client_and_returns_json(monkeypatch):
    fake_client = FakeClient()
    monkeypatch.setattr("dev_to_cli.main.get_client", lambda: fake_client)

    result = runner.invoke(app, ["posts", "unpublish", "3694312"])

    assert result.exit_code == 0
    assert fake_client.post_id == 3694312
    assert '"id": 3694312' in result.stdout
    assert '"published": false' in result.stdout
