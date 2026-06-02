"""Local storage for uploaded image metadata, listing templates, and draft tracking."""
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from .template_validation import validate_template, TemplateValidationError

STORAGE_DIR = Path.home() / ".ebay"
IMAGES_FILE = STORAGE_DIR / "images.json"
TEMPLATES_FILE = STORAGE_DIR / "templates.json"
DRAFTS_FILE = STORAGE_DIR / "drafts.json"


class ImageStorage:
    """Manager for locally stored image metadata."""

    def __init__(self):
        self._ensure_storage_dir()
        self._data = self._load()

    def _ensure_storage_dir(self):
        """Create storage directory if it doesn't exist."""
        STORAGE_DIR.mkdir(parents=True, exist_ok=True)

    def _load(self) -> Dict:
        """Load images from storage file."""
        if IMAGES_FILE.exists():
            return json.loads(IMAGES_FILE.read_text())
        return {"images": []}

    def _save(self):
        """Save images to storage file."""
        IMAGES_FILE.write_text(json.dumps(self._data, indent=2))

    def _prune_expired_images(self) -> List[Dict]:
        """Drop expired image records so list/get only expose live entries."""
        now = datetime.now(timezone.utc)
        active_images = []

        for image in self._data.get("images", []):
            expires_at = datetime.fromisoformat(
                image["expirationDate"].replace("Z", "+00:00")
            )
            if expires_at <= now:
                continue
            active_images.append(image)

        if len(active_images) != len(self._data.get("images", [])):
            self._data["images"] = active_images
            self._save()

        return active_images

    def add_image(self, image_id: str, image_url: str, expiration_date: str,
                  source: str, original: str) -> Dict:
        """Add an uploaded image to local storage."""
        record = {
            "image_id": image_id,
            "imageUrl": image_url,
            "expirationDate": expiration_date,
            "source": source,  # "file" or "url"
            "original": original,  # original path or URL
            "uploaded_at": datetime.utcnow().isoformat() + "Z"
        }
        self._data["images"].append(record)
        self._save()
        return record

    def get_all_images(self) -> List[Dict]:
        """Get all stored images."""
        return self._prune_expired_images()

    def get_image(self, image_id: str) -> Optional[Dict]:
        """Get a specific image by ID."""
        for img in self._prune_expired_images():
            if img.get("image_id") == image_id:
                return img
        return None

    def update_image(self, image_id: str, image_url: str, expiration_date: str):
        """Update image metadata from fresh API response."""
        for img in self._prune_expired_images():
            if img.get("image_id") == image_id:
                img["imageUrl"] = image_url
                img["expirationDate"] = expiration_date
                self._save()
                return


class TemplateStorage:
    """Manager for locally stored listing templates."""

    def __init__(self):
        self._ensure_storage_dir()
        self._data = self._load()

    def _ensure_storage_dir(self):
        """Create storage directory if it doesn't exist."""
        STORAGE_DIR.mkdir(parents=True, exist_ok=True)

    def _load(self) -> Dict:
        """Load templates from storage file."""
        if TEMPLATES_FILE.exists():
            return json.loads(TEMPLATES_FILE.read_text())
        return {"templates": {}}

    def _save(self):
        """Save templates to storage file."""
        TEMPLATES_FILE.write_text(json.dumps(self._data, indent=2))

    def add_template(
        self,
        name: str,
        template: Dict,
        description: Optional[str] = None,
        skip_validation: bool = False,
    ) -> Dict:
        """
        Add or update a template.

        Args:
            name: Template name (must match pattern ^[a-z0-9-]+$)
            template: Template configuration data
            description: Optional description
            skip_validation: If True, skip schema validation (use for legacy templates)

        Returns:
            The saved template record

        Raises:
            TemplateValidationError: If template fails schema validation
        """
        record = {
            "name": name,
            "description": description or "",
            "template": template,
            "created_at": datetime.utcnow().isoformat() + "Z",
            "updated_at": datetime.utcnow().isoformat() + "Z"
        }

        # Preserve created_at if updating
        existing = self._data["templates"].get(name)
        if existing:
            record["created_at"] = existing.get("created_at", record["created_at"])

        # Validate against schema
        if not skip_validation:
            is_valid, errors = validate_template(record)
            if not is_valid:
                raise TemplateValidationError(errors)

        self._data["templates"][name] = record
        self._save()
        return record

    def get_all_templates(self) -> List[Dict]:
        """Get all stored templates as a list."""
        return list(self._data.get("templates", {}).values())

    def get_template(self, name: str) -> Optional[Dict]:
        """Get a specific template by name."""
        return self._data.get("templates", {}).get(name)

    def delete_template(self, name: str) -> bool:
        """Delete a template by name. Returns True if deleted."""
        if name in self._data.get("templates", {}):
            del self._data["templates"][name]
            self._save()
            return True
        return False

    def template_exists(self, name: str) -> bool:
        """Check if a template exists."""
        return name in self._data.get("templates", {})


class DraftStorage:
    """Manager for tracking draft offer IDs locally for fast retrieval."""

    def __init__(self):
        self._ensure_storage_dir()
        self._data = self._load()

    def _ensure_storage_dir(self):
        """Create storage directory if it doesn't exist."""
        STORAGE_DIR.mkdir(parents=True, exist_ok=True)

    def _load(self) -> Dict:
        """Load drafts from storage file."""
        if DRAFTS_FILE.exists():
            return json.loads(DRAFTS_FILE.read_text())
        return {"drafts": {}}

    def _save(self):
        """Save drafts to storage file."""
        DRAFTS_FILE.write_text(json.dumps(self._data, indent=2))

    def add_draft(self, sku: str, offer_id: str) -> Dict:
        """Track a new draft offer."""
        record = {
            "sku": sku,
            "offer_id": offer_id,
            "created_at": datetime.utcnow().isoformat() + "Z",
        }
        self._data["drafts"][sku] = record
        self._save()
        return record

    def remove_draft(self, sku: str) -> bool:
        """Remove a draft (when published or deleted). Returns True if removed."""
        if sku in self._data.get("drafts", {}):
            del self._data["drafts"][sku]
            self._save()
            return True
        return False

    def get_all_drafts(self) -> List[Dict]:
        """Get all tracked drafts."""
        return list(self._data.get("drafts", {}).values())

    def get_draft(self, sku: str) -> Optional[Dict]:
        """Get a specific draft by SKU."""
        return self._data.get("drafts", {}).get(sku)

    def get_offer_ids(self) -> List[str]:
        """Get all tracked offer IDs for fast lookup."""
        return [d["offer_id"] for d in self._data.get("drafts", {}).values()]
