"""Image generation commands for Gemini CLI."""
import base64
from pathlib import Path
from typing import Optional, List
from enum import Enum
import typer

from ..client import get_client
from cli_tools_shared.output import print_success, print_error, print_info, handle_error


class AspectRatio(str, Enum):
    """Supported aspect ratios for image generation."""
    SQUARE = "1:1"
    LANDSCAPE = "16:9"
    PORTRAIT = "9:16"
    STANDARD = "4:3"
    STANDARD_PORTRAIT = "3:4"
    SOCIAL = "1.91:1"  # WordPress/Facebook optimized


class ImageSize(str, Enum):
    """Supported image sizes."""
    SMALL = "1K"
    MEDIUM = "2K"
    LARGE = "4K"


class ImageModel(str, Enum):
    """Available image generation models."""
    NANO_BANANA_PRO = "gemini-3-pro-image-preview"
    NANO_BANANA = "gemini-2.5-flash-image"
    IMAGEN_4 = "imagen-4.0-generate-001"
    IMAGEN_4_ULTRA = "imagen-4.0-ultra-generate-001"
    IMAGEN_4_FAST = "imagen-4.0-fast-generate-001"


app = typer.Typer(help="Image generation with Gemini")


@app.command("generate")
def generate_image(
    prompt: str = typer.Argument(..., help="Text prompt describing the image to generate"),
    output: Path = typer.Option(
        Path("generated_image.png"),
        "--output", "-o",
        help="Output file path"
    ),
    model: ImageModel = typer.Option(
        ImageModel.NANO_BANANA_PRO,
        "--model", "-m",
        help="Image generation model to use"
    ),
    aspect_ratio: AspectRatio = typer.Option(
        AspectRatio.LANDSCAPE,
        "--aspect-ratio", "-ar",
        help="Aspect ratio of generated image"
    ),
    size: ImageSize = typer.Option(
        ImageSize.MEDIUM,
        "--size", "-s",
        help="Output image size/resolution"
    ),
    search: bool = typer.Option(
        False,
        "--search",
        help="Enable Google Search grounding for real-time data"
    ),
    input_images: Optional[List[Path]] = typer.Option(
        None,
        "--input-image", "-i",
        help="Reference image(s) for image editing / multi-image composition. "
             "Repeatable. Only supported by Nano Banana models "
             "(gemini-3-pro-image-preview, gemini-2.5-flash-image)."
    ),
):
    """
    Generate an image from a text prompt using Nano Banana Pro.

    Example:
        gemini image generate "A cyberpunk cityscape at sunset"
        gemini image generate "Cloud infrastructure diagram" -o cloud.png -ar 16:9
        gemini image generate "Current weather in Tokyo visualization" --search
        gemini image generate "Professional blog header" -m nano-banana-pro -s 4K
    """
    try:
        # Validate input image support: only Nano Banana models accept reference images.
        if input_images:
            nano_banana_models = {
                ImageModel.NANO_BANANA_PRO.value,
                ImageModel.NANO_BANANA.value,
            }
            if model.value not in nano_banana_models:
                print_error(
                    f"Model '{model.value}' does not support input images. "
                    f"Use --model gemini-3-pro-image-preview or "
                    f"--model gemini-2.5-flash-image with -i / --input-image."
                )
                raise typer.Exit(1)
            for img_path in input_images:
                if not img_path.exists():
                    print_error(f"Input image not found: {img_path}")
                    raise typer.Exit(1)

        client = get_client()

        print_info(f"Generating image with {model.value}...")
        print_info(f"Aspect ratio: {aspect_ratio.value}, Size: {size.value}")
        if input_images:
            print_info(f"Using {len(input_images)} reference image(s)")

        result = client.generate_image(
            prompt=prompt,
            model=model.value,
            aspect_ratio=aspect_ratio.value,
            image_size=size.value,
            use_search=search,
            input_images=input_images,
        )

        # Save the first generated image
        if result["images"]:
            image_data = result["images"][0]["data"]
            mime_type = result["images"][0]["mime_type"]

            # Determine file extension from mime type
            ext_map = {
                "image/png": ".png",
                "image/jpeg": ".jpg",
                "image/webp": ".webp",
            }
            ext = ext_map.get(mime_type, ".png")

            # Update output path with correct extension if needed
            output_path = output
            if output_path.suffix.lower() not in [".png", ".jpg", ".jpeg", ".webp"]:
                output_path = output_path.with_suffix(ext)

            # Handle base64 encoded data
            if isinstance(image_data, str):
                image_bytes = base64.b64decode(image_data)
            else:
                image_bytes = image_data

            output_path.write_bytes(image_bytes)
            print_success(f"Image saved to: {output_path}")

            # Print any accompanying text
            if result.get("text"):
                print_info(f"\nModel response: {result['text']}")

            # Print image count if multiple
            if len(result["images"]) > 1:
                print_info(f"\nGenerated {len(result['images'])} images. Additional images not saved.")

    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("models")
def list_image_models():
    """
    List available image generation models.

    Example:
        gemini image models
    """
    print_info("Available image generation models:\n")
    models = [
        ("gemini-3-pro-image-preview", "Nano Banana Pro", "Highest quality, 4K support, grounded generation"),
        ("gemini-2.5-flash-image", "Nano Banana", "Faster generation, good quality"),
        ("imagen-4.0-generate-001", "Imagen 4", "Vertex AI image generation"),
        ("imagen-4.0-ultra-generate-001", "Imagen 4 Ultra", "Ultra quality Imagen"),
        ("imagen-4.0-fast-generate-001", "Imagen 4 Fast", "Fast Imagen generation"),
    ]

    for model_id, name, description in models:
        print(f"  {name}")
        print(f"    ID: {model_id}")
        print(f"    {description}")
        print()


COMMAND_CREDENTIALS = {
    "generate": [
        "custom"
    ],
    "models": [
        "custom"
    ]
}
