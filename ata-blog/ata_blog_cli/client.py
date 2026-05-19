"""ATA Blog wrapper client using subprocess to call wordpress and notion CLIs."""
import json
import os
import subprocess
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import get_config


class ClientError(Exception):
    """Custom exception for ATA Blog wrapper errors."""
    pass


class AtaBlogClient:
    """Wrapper client for wordpress and notion CLIs."""

    def __init__(self):
        self.config = get_config()
        self._wordpress_checked = False

        # Only check Notion CLI on init - WordPress is checked lazily when needed
        if not self.config.is_notion_available():
            raise ClientError("notion CLI not found. Install it first.")

    def _ensure_wordpress(self):
        """Lazily check WordPress CLI availability on first WordPress operation."""
        if not self._wordpress_checked:
            if not self.config.is_wordpress_available():
                raise ClientError("wordpress CLI not found. Install it first.")
            self._wordpress_checked = True

    def _run_wordpress(self, args: List[str], timeout: int = 60) -> subprocess.CompletedProcess:
        """Run a wordpress CLI command."""
        self._ensure_wordpress()
        cmd = ["wordpress"] + args
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode != 0:
            raise ClientError(f"wordpress error: {result.stderr.strip()}")
        return result

    def _run_notion(self, args: List[str], timeout: int = 60) -> subprocess.CompletedProcess:
        """Run a notion CLI command."""
        cmd = ["notion"] + args
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode != 0:
            # notion CLI returns exit code 1 with "No pages found." which is not an error
            if "No pages found" in result.stdout:
                # Return empty array for list commands
                result.stdout = "[]"
                return result
            raise ClientError(f"notion error: {result.stderr.strip()}")
        return result

    @staticmethod
    def _validate_featured_image(featured_image: Optional[str]) -> Path:
        """Validate the required local featured image before publishing."""
        if not featured_image:
            raise ClientError("Featured image is required for publishing. Run image-gen first.")

        image_path = Path(featured_image)
        if not image_path.exists():
            raise ClientError(f"Featured image not found: {featured_image}")
        if not image_path.is_file():
            raise ClientError(f"Featured image path is not a file: {featured_image}")
        if image_path.stat().st_size == 0:
            raise ClientError(f"Featured image file is empty: {featured_image}")

        allowed_extensions = {".webp", ".png", ".jpg", ".jpeg"}
        if image_path.suffix.lower() not in allowed_extensions:
            raise ClientError(
                "Featured image must be a WebP, PNG, or JPEG file: "
                f"{featured_image}"
            )

        return image_path

    # WordPress passthrough methods
    def wordpress_auth_status(self) -> Dict[str, Any]:
        result = self._run_wordpress(["auth", "status"])
        return json.loads(result.stdout)

    def list_posts(self, limit: int = 100, filters: Optional[Dict] = None) -> List[Dict]:
        args = ["posts", "list", "--limit", str(limit)]
        if filters:
            filter_str = ",".join(f"{k}={v}" for k, v in filters.items())
            args.extend(["--filter", filter_str])
        result = self._run_wordpress(args)
        return json.loads(result.stdout)

    # Notion article methods
    def list_articles(
        self,
        status: Optional[str] = None,
        limit: int = 100,
        filters: Optional[List[str]] = None,
    ) -> List[Dict]:
        """List articles from Notion database.

        Args:
            status: Single status or pipe-separated statuses (e.g., "Draft" or "Draft|Review")
            limit: Maximum number of results
            filters: List of filter strings (field:op:value format)
        """
        args = ["database", "page", "list", "-d", self.config.notion_database_id, "--limit", str(limit)]
        if status:
            # Check if multiple statuses (contains |)
            if "|" in status:
                args.extend(["--filter", f"Status:in:{status}"])
            else:
                args.extend(["--filter", f"Status:eq:{status}"])

        # Pass through additional filters to notion CLI
        if filters:
            for f in filters:
                # Normalize 'contains' operator to 'ilike' with wildcards
                if ":contains:" in f.lower():
                    parts = f.split(":", 2)
                    if len(parts) == 3:
                        field, _, value = parts
                        f = f"{field}:ilike:%{value}%"
                args.extend(["--filter", f])

        result = self._run_notion(args)
        return json.loads(result.stdout)

    def get_article(self, page_id: str) -> Dict[str, Any]:
        result = self._run_notion(["database", "page", "get", page_id, "--include-blocks"])
        return json.loads(result.stdout)

    def get_article_markdown(self, page_id: str) -> str:
        """Get article content as markdown."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            temp_path = f.name

        try:
            self._run_notion([
                "database", "page", "get", page_id,
                "--include-blocks", "--markdown", "--out-file", temp_path
            ])
            return Path(temp_path).read_text()
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def get_article_comments(self, page_id: str, with_context: bool = True) -> List[Dict]:
        """Get comments on an article page.

        Args:
            page_id: Notion page ID
            with_context: Include parent block text as context (default: True)

        Returns:
            List of comment objects with text and context
        """
        args = ["comments", "list", "--page-id", page_id]
        if with_context:
            args.append("--with-context")
        result = self._run_notion(args)
        return json.loads(result.stdout)

    def create_article_comment(self, page_id: str, body: str) -> Dict[str, Any]:
        """Create a comment on an article page.

        Args:
            page_id: Notion page ID
            body: Comment text content

        Returns:
            Created comment object from the Notion API
        """
        if not body or not body.strip():
            raise ClientError("Comment body must not be empty")
        args = ["comments", "create", body, "--page-id", page_id]
        result = self._run_notion(args)
        return json.loads(result.stdout)

    def get_article_comment(self, comment_id: str) -> Dict[str, Any]:
        """Get a single comment by its Notion comment ID."""
        result = self._run_notion(["comments", "get", comment_id])
        return json.loads(result.stdout)

    # Property type mapping for ATA Blog database
    # These must match the actual Notion database schema
    PROPERTY_TYPES = {
        "Title": "title",
        "Category": "select",
        "Type": "select",
        "Tags": "multi_select",
        "Editor": "multi_select",
        "Rejection Reasons": "multi_select",
        "Schema Type": "multi_select",
        "Intro Archetype": "select",
        "Keywords": "rich_text",
        "Excerpt": "rich_text",
        "Link Validation Task ID": "rich_text",
        "Fact Check Task ID": "rich_text",
        "Author Paid": "checkbox",
        "Stage Date": "date",
        "Publish Date": "date",
        "Published URL": "url",
    }

    def update_article(
        self,
        page_id: str,
        status: Optional[str] = None,
        properties: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """
        Update article properties in Notion.

        Args:
            page_id: Notion page ID
            status: New status value (will be prefixed with "Status:" if needed)
            properties: Dict of property updates in format {"PropertyName": "value"}

        Returns dict with updated page info
        """
        args = ["database", "page", "update", page_id]

        if status:
            # Auto-prefix "Status:" if not already present
            status_value = status if ":" in status else f"Status:{status}"
            args.extend(["--status", status_value])

        if properties:
            # Collect properties that must be sent as raw Notion property JSON.
            raw_json_properties = {}

            for prop_name, prop_value in properties.items():
                prop_type = self.PROPERTY_TYPES.get(prop_name)

                if prop_type == "title":
                    # Title type requires raw JSON via --properties
                    raw_json_properties[prop_name] = {
                        "title": [{"type": "text", "text": {"content": prop_value}}]
                    }
                elif prop_type == "select":
                    args.extend(["--select", f"{prop_name}:{prop_value}"])
                elif prop_type == "multi_select":
                    # Parse comma-separated values into list of names
                    values = [v.strip() for v in prop_value.split(",") if v.strip()]
                    raw_json_properties[prop_name] = {
                        "multi_select": [{"name": v} for v in values]
                    }
                elif prop_type == "date":
                    raw_json_properties[prop_name] = {
                        "date": {"start": prop_value}
                    }
                elif prop_type == "checkbox":
                    args.extend(["--checkbox", f"{prop_name}:{prop_value}"])
                elif prop_type == "url":
                    args.extend(["--url", f"{prop_name}:{prop_value}"])
                elif prop_value.lower() in ("true", "false"):
                    # Fallback checkbox detection
                    args.extend(["--checkbox", f"{prop_name}:{prop_value}"])
                elif prop_value.replace(".", "").replace("-", "").isdigit():
                    args.extend(["--number", f"{prop_name}:{prop_value}"])
                else:
                    args.extend(["--text", f"{prop_name}:{prop_value}"])

            if raw_json_properties:
                args.extend(["--properties", json.dumps(raw_json_properties)])

        result = self._run_notion(args)
        return json.loads(result.stdout)

    DEFAULT_IDEA_TEMPLATE_ID = "2e05d9c8-5b2b-8065-8aca-e8da0e179b97"

    VALID_CATEGORIES = ("IT Ops", "Home Ops", "DevOps", "Cloud", "Information Security", "Ebook")

    def create_article(
        self,
        title: str,
        excerpt: str,
        category: str,
        keywords: Optional[str] = None,
        post_type: str = "Standard",
        status: Optional[str] = None,
        template_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a new article in the Notion database.

        Args:
            title: Article title
            excerpt: Article description/synopsis
            category: Category (must be one of VALID_CATEGORIES)
            keywords: Optional comma-separated SEO keywords
            post_type: Post type (default: Standard)
            status: Optional status (uses template default if not set)
            template_id: Optional template ID (defaults to Standard ATA Tutorial AI-Created Idea)
        """
        if category not in self.VALID_CATEGORIES:
            raise ClientError(
                f"Invalid category '{category}'. Must be one of: {', '.join(self.VALID_CATEGORIES)}"
            )

        # NOTE: When --from-template is used, --select flags for Category/Type are
        # silently dropped by the notion CLI. Setting them via --properties JSON works.
        properties: Dict[str, Any] = {
            "Category": {"select": {"name": category}},
            "Type": {"select": {"name": post_type}},
            "Excerpt": {"rich_text": [{"text": {"content": excerpt}}]},
        }
        if keywords:
            properties["Keywords"] = {"rich_text": [{"text": {"content": keywords}}]}

        args = [
            "database", "page", "create", self.config.notion_database_id,
            "--title", title,
            "--from-template", template_id or self.DEFAULT_IDEA_TEMPLATE_ID,
            "--properties", json.dumps(properties),
        ]
        if status:
            args.extend(["--status", f"Status:{status}"])

        result = self._run_notion(args)
        return json.loads(result.stdout)

    def set_article_content(self, page_id: str, file_path: str) -> Dict[str, Any]:
        """Replace article content with markdown from file."""
        result = self._run_notion([
            "database", "page", "content", "set", page_id,
            "--file", file_path
        ])
        return json.loads(result.stdout) if result.stdout.strip() else {"success": True}

    def append_article_content(self, page_id: str, file_path: str) -> Dict[str, Any]:
        """Append markdown content to article."""
        result = self._run_notion([
            "database", "page", "content", "append", page_id,
            "--file", file_path
        ])
        return json.loads(result.stdout) if result.stdout.strip() else {"success": True}

    def search_articles(self, query: str, status: Optional[str] = None, limit: int = 100) -> List[Dict]:
        """Search articles by title."""
        args = ["database", "page", "list", "-d", self.config.notion_database_id, "--limit", str(limit)]
        # Use 'like' operator with wildcards for title search
        args.extend(["--filter", f"Title:like:%{query}%"])
        if status:
            # Check if multiple statuses (contains |)
            if "|" in status:
                args.extend(["--filter", f"Status:in:{status}"])
            else:
                args.extend(["--filter", f"Status:eq:{status}"])
        result = self._run_notion(args)
        return json.loads(result.stdout)

    @staticmethod
    def get_valid_statuses() -> List[str]:
        """Return list of valid article statuses for ATA pipeline."""
        return [
            "Idea",
            "Good Idea",
            "Idea Rejected",
            "Research",
            "SERP Analysis",
            "Draft",
            "Developmental Review",
            "Human Review",
            "Demo Testing",
            "Link Validation",
            "Fact Check",
            "Final Human Review",
            "Ready to Publish",
            "Published",
            "Archived",
        ]

    def resolve_category_by_name(self, name: str) -> int:
        """Find WordPress category ID by exact name match."""
        result = self._run_wordpress(["categories", "list"])
        categories = json.loads(result.stdout)
        for cat in categories:
            if cat.get("name", "").lower() == name.lower():
                return cat["id"]
        raise ClientError(f"Category not found: {name}")

    def resolve_tag_by_name(self, name: str) -> int:
        """Find WordPress tag ID by exact name match."""
        result = self._run_wordpress(["tags", "list", "--limit", "1000"])
        tags = json.loads(result.stdout)
        for tag in tags:
            if tag.get("name", "").lower() == name.lower():
                return tag["id"]
        raise ClientError(f"Tag not found: {name}")

    def check_duplicate_post(self, slug: str) -> bool:
        """Check if a WordPress post with this slug already exists."""
        result = self._run_wordpress(["posts", "list", "--filter", f"slug:eq:{slug}"])
        posts = json.loads(result.stdout)
        return len(posts) > 0

    # Schedule reservation directory for preventing race conditions
    _RESERVATION_DIR = Path.home() / ".cache" / "ata-blog" / "schedule-reservations"

    def _read_schedule_reservations(self) -> List[datetime]:
        """Read pending schedule reservations, cleaning up expired ones."""
        times = []
        if not self._RESERVATION_DIR.exists():
            return times
        for f in self._RESERVATION_DIR.glob("*.json"):
            try:
                data = json.loads(f.read_text())
                expires = datetime.fromisoformat(data["expires"])
                if expires < datetime.now():
                    f.unlink()  # Expired reservation
                else:
                    times.append(datetime.fromisoformat(data["slot"]))
            except (json.JSONDecodeError, KeyError, ValueError):
                f.unlink()  # Corrupt reservation
        return times

    def _create_schedule_reservation(self, slot: str) -> None:
        """Create a temporary reservation for a schedule slot (expires in 10 min)."""
        self._RESERVATION_DIR.mkdir(parents=True, exist_ok=True)
        reservation = {
            "slot": slot,
            "expires": (datetime.now() + timedelta(minutes=10)).isoformat(),
            "pid": os.getpid(),
        }
        path = self._RESERVATION_DIR / f"{os.getpid()}_{int(time.time())}.json"
        path.write_text(json.dumps(reservation))

    def clear_schedule_reservation(self) -> None:
        """Clear schedule reservations created by this process."""
        if self._RESERVATION_DIR.exists():
            for f in self._RESERVATION_DIR.glob(f"{os.getpid()}_*.json"):
                f.unlink()

    def find_next_schedule_slot(self) -> str:
        """
        Find next available publication slot respecting:
        - Max 2 posts per weekday
        - 4+ hour gap between posts
        - No weekends (roll to Monday)
        - Pending reservations from concurrent processes

        Returns ISO 8601 datetime string.
        """
        # Get scheduled posts
        scheduled_result = self._run_wordpress(["posts", "list", "--filter", "status:eq:future", "--limit", "100"])
        scheduled = json.loads(scheduled_result.stdout)

        # Get recently published posts (last 7 days for safety)
        published_result = self._run_wordpress(["posts", "list", "--filter", "status:eq:publish", "--limit", "20"])
        published = json.loads(published_result.stdout)

        # Parse dates from all posts
        occupied_times = []
        for post in scheduled + published:
            date_str = post.get("date") or post.get("date_gmt")
            if date_str:
                try:
                    dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                    occupied_times.append(dt.replace(tzinfo=None))
                except ValueError:
                    continue

        # Include pending reservations from concurrent processes
        occupied_times.extend(self._read_schedule_reservations())

        # Start from now
        now = datetime.now()
        candidate = now.replace(minute=0, second=0, microsecond=0)

        # If before 9am, start at 9am
        if candidate.hour < 9:
            candidate = candidate.replace(hour=9)

        max_iterations = 100  # Safety limit
        for _ in range(max_iterations):
            # Skip weekends (5=Saturday, 6=Sunday)
            if candidate.weekday() >= 5:
                days_until_monday = 7 - candidate.weekday()
                candidate = (candidate + timedelta(days=days_until_monday)).replace(hour=9, minute=0)
                continue

            # Count posts on same day
            same_day = [t for t in occupied_times if t.date() == candidate.date()]
            if len(same_day) >= 2:
                candidate = (candidate + timedelta(days=1)).replace(hour=9, minute=0)
                continue

            # Check 4+ hour gap
            conflicts = [t for t in occupied_times if abs((t - candidate).total_seconds()) < 4 * 3600]
            if conflicts:
                candidate = candidate + timedelta(hours=4)
                # If pushed past reasonable hours (after 5pm), go to next day
                if candidate.hour >= 17:
                    candidate = (candidate + timedelta(days=1)).replace(hour=9, minute=0)
                continue

            # Found valid slot - reserve it before returning
            slot = candidate.strftime("%Y-%m-%dT%H:%M:%S")
            self._create_schedule_reservation(slot)
            return slot

        raise ClientError("Could not find available schedule slot within iteration limit")

    def publish_article(
        self,
        page_id: str,
        status: str = "draft",
        slug: Optional[str] = None,
        date: Optional[str] = None,
        auto_schedule: bool = False,
        check_duplicates: bool = True,
        featured_image: Optional[str] = None,
        force: bool = False,
    ) -> Dict[str, Any]:
        """
        Publish a Notion article to WordPress.

        Args:
            page_id: Notion page ID
            status: WordPress status (draft, publish, future)
            slug: Optional custom URL slug (auto-generated from title if not provided)
            date: Optional schedule date (ISO 8601). If auto_schedule, this is ignored.
            auto_schedule: If True, automatically find next available slot
            check_duplicates: If True, error if slug already exists
            featured_image: Optional path to featured image file to upload and attach
            force: If True, skip the already-published check

        Returns dict with wordpress_post, notion_page_id, schedule info,
        and optional featured_image/schema status
        """
        warnings = []

        # 0. Validate featured image before doing anything (fail early)
        image_path = self._validate_featured_image(featured_image)

        # 1. Get article metadata from Notion
        article = self.get_article(page_id)

        # 1b. Check if already published (unless --force)
        if not force:
            published_url = article.get("Published URL")
            if published_url:
                raise ClientError(
                    f"Post already published at: {published_url}. "
                    f"Use --force to republish."
                )
        title = article.get("Title") or article.get("title") or "Untitled"

        # 2. Validate required fields
        keywords = article.get("Keywords", "")
        category_name = article.get("Category")
        tags_str = article.get("Tags", "")
        excerpt = article.get("Excerpt", "")

        missing = []
        if not keywords:
            missing.append("Keywords")
        if not category_name:
            missing.append("Category")
        if not tags_str:
            missing.append("Tags")
        if not excerpt:
            missing.append("Excerpt")

        if missing:
            raise ClientError(f"Missing required Notion fields: {', '.join(missing)}")

        # 2b. Read Schema Type from Notion (already fetched above)
        schema_type_raw = article.get("Schema Type", "")
        # Schema Type may be a comma-separated multi_select value
        if schema_type_raw:
            schema_type_str = schema_type_raw.split(",")[0].strip()
        else:
            schema_type_str = "Article"
            warnings.append("Schema Type missing in Notion, defaulting to 'Article'")

        # 3. Upload featured image before creating post (fail early)
        from .utils.images import upload_to_wordpress
        try:
            featured_image_result = upload_to_wordpress(image_path)
        except RuntimeError as e:
            raise ClientError(f"Featured image upload failed: {e}")
        if not featured_image_result.get("id"):
            raise ClientError("Featured image upload did not return a WordPress media ID")

        # 4. Generate slug (or use custom) and check for duplicates
        import re
        if slug:
            # Use provided custom slug - validate and clean it
            slug = re.sub(r'[^a-z0-9-]', '', slug.lower())[:50].rstrip('-')
        else:
            # Auto-generate slug from title
            # Stop words to remove from slugs (prepositions, articles, conjunctions)
            stop_words = {
                'a', 'an', 'the', 'and', 'or', 'but', 'nor', 'for', 'yet', 'so',
                'to', 'of', 'in', 'on', 'at', 'by', 'with', 'from', 'as', 'into',
                'through', 'during', 'before', 'after', 'above', 'below', 'between',
                'under', 'over', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
                'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could',
                'should', 'may', 'might', 'must', 'shall', 'can', 'your', 'you',
                'how', 'what', 'when', 'where', 'why', 'which', 'who', 'whom',
            }
            # Split title into words, filter out stop words
            words = title.lower().split()
            filtered_words = [w for w in words if w not in stop_words]
            # Clean each word (remove special chars)
            cleaned_words = [re.sub(r'[^a-z0-9]', '', w) for w in filtered_words]
            cleaned_words = [w for w in cleaned_words if w]  # Remove empty strings
            # Build slug by adding words until we hit 50 char limit
            slug_parts = []
            current_length = 0
            for word in cleaned_words:
                # +1 for the hyphen (except first word)
                addition = len(word) + (1 if slug_parts else 0)
                if current_length + addition <= 50:
                    slug_parts.append(word)
                    current_length += addition
                else:
                    break
            slug = '-'.join(slug_parts)
        if check_duplicates and self.check_duplicate_post(slug):
            raise ClientError(f"WordPress post with slug '{slug}' already exists")

        # 5. Resolve category and tags to IDs
        category_id = self.resolve_category_by_name(category_name)
        tag_names = [t.strip() for t in tags_str.split(",") if t.strip()]
        tag_ids = [self.resolve_tag_by_name(name) for name in tag_names]

        # 6. Determine schedule date
        effective_date = None
        effective_status = status
        if auto_schedule:
            effective_date = self.find_next_schedule_slot()
            effective_status = "future"
        elif date:
            effective_date = date
            effective_status = "future"

        # 7. Get content as markdown
        markdown_content = self.get_article_markdown(page_id)

        # 8. Process images - download from Notion, upload to WordPress
        from .utils.images import process_images_for_wordpress
        markdown_content = process_images_for_wordpress(
            markdown_content=markdown_content,
            article_slug=slug,
            verbose=True
        )

        # 9. Save to temp file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write(markdown_content)
            temp_path = f.name

        try:
            # 10. Build wordpress CLI command
            args = [
                "posts", "create",
                "--from-markdown", temp_path,
                "--title", title,
                "--slug", slug,
                "--status", effective_status,
                "--categories", str(category_id),
                "--tags", ",".join(str(t) for t in tag_ids),
                "--excerpt", excerpt,
                "--meta", f"rank_math_focus_keyword={keywords}",
            ]
            if effective_date:
                args.extend(["--date", effective_date])

            result = self._run_wordpress(args)
            post = json.loads(result.stdout)
            post_id = post.get("id")

            # 10b. Clear schedule reservation now that post is committed to WordPress
            if auto_schedule:
                self.clear_schedule_reservation()

            # 11. Attach featured image and apply schema in a single update call
            fi_status = {"attached": False}
            schema_status = {"type": schema_type_str, "applied": False}

            if featured_image_result or schema_type_str:
                update_args = ["posts", "update"]

                if featured_image_result:
                    update_args.extend(["--featured-media", str(featured_image_result["id"])])
                    fi_status["media_id"] = featured_image_result["id"]
                    fi_status["source_url"] = featured_image_result.get("source_url")

                # Build schema JSON
                from .commands.schema import _build_schema_json, SchemaType, ProficiencyLevel
                schema_type_map = {
                    "Article": SchemaType.ARTICLE,
                    "TechArticle": SchemaType.TECH_ARTICLE,
                    "Review": SchemaType.REVIEW,
                }
                schema_enum = schema_type_map.get(schema_type_str, SchemaType.ARTICLE)
                proficiency = ProficiencyLevel.INTERMEDIATE if schema_enum == SchemaType.TECH_ARTICLE else None
                schema_json = _build_schema_json(schema_type=schema_enum, proficiency=proficiency)
                update_args.extend(["--meta", f"rank_math_schemas={schema_json}"])
                update_args.append(str(post_id))

                update_result = self._run_wordpress(update_args)
                updated_post = json.loads(update_result.stdout)
                attached_media_id = int(updated_post.get("featured_media") or 0)
                expected_media_id = int(featured_image_result["id"])
                if attached_media_id != expected_media_id:
                    raise ClientError(
                        "Featured image attachment failed: "
                        f"post {post_id} has featured_media "
                        f"{attached_media_id}, expected {expected_media_id}"
                    )
                fi_status["attached"] = True
                schema_status["applied"] = True

            # 12. Update Notion with Published status and URL
            wp_url = post.get("link") or post.get("url", "")
            wp_edit_url = f"https://adamtheautomator.com/wp-admin/post.php?post={post_id}&action=edit"
            self._run_notion([
                "database", "page", "update", page_id,
                "--status", "Status:Published",
                "--url", f"Published URL:{wp_url}"
            ])

            result_dict = {
                "wordpress_post": post,
                "notion_page_id": page_id,
                "status": effective_status,
                "scheduled_date": effective_date,
                "wordpress_url": wp_url,
                "wordpress_edit_url": wp_edit_url,
                "warnings": warnings,
            }

            result_dict["featured_image"] = fi_status

            if schema_type_str:
                result_dict["schema"] = schema_status

            return result_dict
        finally:
            Path(temp_path).unlink(missing_ok=True)


_client: Optional[AtaBlogClient] = None


def get_client() -> AtaBlogClient:
    global _client
    if _client is None:
        _client = AtaBlogClient()
    return _client
