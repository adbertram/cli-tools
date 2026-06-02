"""Images commands for eBay CLI.

Uses the eBay Commerce Media API to upload and manage images.
API Docs: https://developer.ebay.com/api-docs/commerce/media/resources/image/methods/createImageFromFile
"""
COMMAND_CREDENTIALS = {
    "upload": ["oauth_authorization_code"],
    "list": ["oauth_authorization_code"],
    "get": ["oauth_authorization_code"],
}

import typer
from pathlib import Path
from typing import Optional, List

from ..client import get_client
from cli_tools_shared.output import print_json, print_table, handle_error, print_success, print_info, print_error, print_warning
from ..storage import ImageStorage
from cli_tools_shared.filters import validate_filters, apply_filters, FilterValidationError
from ..parsers import format_local_time
from ..properties import (
    add_image_property_aliases,
    validate_and_filter_properties,
    PropertyValidationError,
)

app = typer.Typer(help="Manage eBay images via Media API")


def _image_record(image: dict) -> dict:
    """Expose canonical list properties for stored image records."""
    return {
        **image,
        "id": image.get("image_id"),
        "name": image.get("original"),
    }


@app.command("upload")
def images_upload(
    file: Optional[str] = typer.Option(
        None, "--file", "-f",
        help="Local file path(s) to upload (comma-separated for multiple)"
    ),
    url: Optional[str] = typer.Option(
        None, "--url", "-u",
        help="External image URL(s) to upload (comma-separated for multiple)"
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display results as table"),
):
    """
    Upload images to eBay for use in listings.

    Images are hosted on eBay's servers and expire after 30 days if not used
    in a listing. Upload results are stored locally in ~/.ebay/images.json.

    Use --file for local files or --url for external URLs (cannot mix).
    Multiple images can be uploaded by comma-separating paths or URLs.

    Examples:
        ebay images upload --file /path/to/image.jpg
        ebay images upload --file "/path/one.jpg,/path/two.jpg"
        ebay images upload --url "https://example.com/image.jpg"
        ebay images upload --url "https://a.com/1.jpg,https://b.com/2.jpg" --table
    """
    # Validation: exactly one of --file or --url must be provided
    if not file and not url:
        print_error("Must specify either --file or --url")
        raise typer.Exit(1)

    if file and url:
        print_error("Cannot use both --file and --url in same command")
        raise typer.Exit(1)

    try:
        client = get_client()
        storage = ImageStorage()

        results = []
        errors = []

        if file:
            # Parse comma-separated file paths
            file_paths = [p.strip() for p in file.split(",")]

            for path in file_paths:
                try:
                    # Validate file exists
                    if not Path(path).exists():
                        errors.append({"original": path, "error": "File not found"})
                        continue

                    result = client.upload_image_from_file(path)
                    record = storage.add_image(
                        image_id=result["image_id"],
                        image_url=result["imageUrl"],
                        expiration_date=result["expirationDate"],
                        source="file",
                        original=path
                    )
                    results.append(record)
                    print_success(f"Uploaded: {path}")

                except Exception as e:
                    errors.append({"original": path, "error": str(e)})
                    print_error(f"Failed to upload {path}: {e}")

        else:  # url
            # Parse comma-separated URLs
            urls = [u.strip() for u in url.split(",")]

            for image_url in urls:
                try:
                    result = client.upload_image_from_url(image_url)
                    record = storage.add_image(
                        image_id=result["image_id"],
                        image_url=result["imageUrl"],
                        expiration_date=result["expirationDate"],
                        source="url",
                        original=image_url
                    )
                    results.append(record)
                    print_success(f"Uploaded: {image_url}")

                except Exception as e:
                    errors.append({"original": image_url, "error": str(e)})
                    print_error(f"Failed to upload {image_url}: {e}")

        # Display 30-day expiration warning
        if results:
            print_warning("Uploaded images expire after 30 days if not used in a listing.")

        # Output results
        if table:
            if results:
                for r in results:
                    r["expirationDate"] = format_local_time(r.get("expirationDate", ""))
                print_table(
                    results,
                    ["image_id", "imageUrl", "expirationDate", "source", "original"],
                    ["Image ID", "URL", "Expires", "Source", "Original"]
                )
        else:
            output = {
                "uploaded": results,
                "errors": errors,
                "total_uploaded": len(results),
                "total_errors": len(errors)
            }
            print_json(output)

        # Exit with error code if any uploads failed
        if errors and not results:
            raise typer.Exit(1)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("list")
def images_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of results to return"),
    filters: Optional[List[str]] = typer.Option(
        None, "--filter", "-f",
        help="Filter (field:op:value). Operators: eq, ne, gt, gte, lt, lte, in, nin, like, ilike, null, notnull"
    ),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p",
        help="Comma-separated list of fields to include"
    ),
):
    """
    List all locally-stored uploaded images.

    Shows images stored in ~/.ebay/images.json from previous uploads.

    Available fields: id, name, image_id, imageUrl, expirationDate, source, original, uploaded_at

    Examples:
        ebay images list
        ebay images list --table
        ebay images list --limit 10
        ebay images list --properties "image_id,imageUrl,expirationDate"
        ebay images list --filter "source:eq:file"
    """
    try:
        storage = ImageStorage()
        images = storage.get_all_images()

        if not images:
            if table:
                print_table(
                    [],
                    ["image_id", "imageUrl", "expirationDate", "source", "original", "uploaded_at"],
                    ["Image ID", "URL", "Expires", "Source", "Original", "Uploaded"]
                )
            else:
                print_json([])
            return

        # Validate and apply client-side filters if provided
        if filters:
            try:
                validated_filters = validate_filters(filters)
                images = apply_filters(images, validated_filters)
            except FilterValidationError as e:
                print_error(str(e))
                raise typer.Exit(1)

        images = [_image_record(image) for image in images]

        # Apply properties filter if specified
        if properties:
            try:
                images = validate_and_filter_properties(
                    add_image_property_aliases(images),
                    properties,
                )
            except PropertyValidationError as e:
                print_error(str(e))
                raise typer.Exit(1)

        # Apply limit (client-side since this is local storage)
        images = images[:limit]

        if table:
            for img in images:
                img["expirationDate"] = format_local_time(img.get("expirationDate", ""))
                img["uploaded_at"] = format_local_time(img.get("uploaded_at", ""))
            print_table(
                images,
                ["image_id", "imageUrl", "expirationDate", "source", "original", "uploaded_at"],
                ["Image ID", "URL", "Expires", "Source", "Original", "Uploaded"]
            )
        else:
            print_json(images)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def images_get(
    image_id: str = typer.Argument(..., help="The eBay image ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get fresh image metadata from eBay API.

    Fetches current imageUrl and expirationDate from eBay.
    If the image exists in local storage, updates the stored metadata.

    Examples:
        ebay images get abc123
        ebay images get abc123 --table
    """
    try:
        client = get_client()
        storage = ImageStorage()

        # Fetch from API
        result = client.get_image(image_id)

        # Update local storage if image exists there
        local_image = storage.get_image(image_id)
        if local_image:
            storage.update_image(
                image_id=image_id,
                image_url=result["imageUrl"],
                expiration_date=result["expirationDate"]
            )
            print_info("Local storage updated with fresh metadata.")

        if table:
            data = [{
                "image_id": image_id,
                "imageUrl": result["imageUrl"],
                "expirationDate": format_local_time(result["expirationDate"]),
            }]
            print_table(
                data,
                ["image_id", "imageUrl", "expirationDate"],
                ["Image ID", "URL", "Expires"]
            )
        else:
            result["image_id"] = image_id
            print_json(result)

    except Exception as e:
        raise typer.Exit(handle_error(e))
