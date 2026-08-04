"""Parse and prepare chat attachments (images, Java, PDFs)."""

from __future__ import annotations

import base64
import logging
import mimetypes
from dataclasses import dataclass, field
from io import BytesIO
from typing import Any

from werkzeug.datastructures import FileStorage

from config import running_on_vercel

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {
    ".java",
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".txt",
    ".py",
    ".md",
    ".json",
    ".xml",
    ".yml",
    ".yaml",
    ".cs",
    ".js",
    ".ts",
    ".sql",
    ".html",
    ".css",
}

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg"}
TEXT_EXTENSIONS = ALLOWED_EXTENSIONS - IMAGE_EXTENSIONS - {".pdf"}
CODE_EXTENSIONS = {
    ".java",
    ".py",
    ".js",
    ".ts",
    ".cs",
    ".sql",
    ".html",
    ".css",
    ".json",
    ".xml",
    ".yml",
    ".yaml",
}

# Models known to accept image_url content parts on Groq.
KNOWN_VISION_MODELS = {
    "qwen/qwen3.6-27b",
    "meta-llama/llama-4-scout-17b-16e-instruct",
    "meta-llama/llama-4-maverick-17b-128e-instruct",
    "openai/gpt-4o-mini",
    "openai/gpt-4o",
    "google/gemini-2.0-flash-001",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-1.5-flash",
    "gemini-1.5-pro",
}

# Preferred models by provider for each attachment class.
VISION_FALLBACKS: dict[str, str] = {
    "groq": "qwen/qwen3.6-27b",
    "gemini": "gemini-2.0-flash",
    "openrouter": "openai/gpt-4o-mini",
    "mistral": "mistral-small-latest",
}

PDF_PREFERRED: dict[str, str] = {
    "groq": "llama-3.3-70b-versatile",
    "sambanova": "Meta-Llama-3.3-70B-Instruct",
    "gemini": "gemini-2.0-flash",
    "openrouter": "x-ai/grok-4.5",
    "mistral": "mistral-small-latest",
    "cohere": "command-a-03-2025",
}

CODE_PREFERRED: dict[str, str] = {
    "groq": "llama-3.3-70b-versatile",
    "sambanova": "DeepSeek-R1-Distill-Llama-70B",
    "gemini": "gemini-2.0-flash",
    "openrouter": "qwen/qwen-2.5-72b-instruct",
    "mistral": "codestral-latest",
    "cohere": "command-r-plus-08-2024",
}

MAX_FILES = 5
# Vercel caps request bodies around 4.5MB; stay safely under that when hosted.
MAX_FILE_BYTES = (3 * 1024 * 1024) if running_on_vercel() else (8 * 1024 * 1024)
MAX_TEXT_CHARS = 48000
MAX_PDF_CHARS = 40000
MAX_PDF_PAGES = 40


class AttachmentError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass
class ProcessedAttachment:
    filename: str
    kind: str  # image | text | pdf
    extension: str
    mime_type: str
    text: str = ""
    language: str = ""
    data_url: str | None = None
    page_count: int | None = None


@dataclass
class AttachmentBundle:
    attachments: list[ProcessedAttachment] = field(default_factory=list)

    @property
    def has_images(self) -> bool:
        return any(item.kind == "image" for item in self.attachments)

    @property
    def has_pdf(self) -> bool:
        return any(item.kind == "pdf" for item in self.attachments)

    @property
    def has_code(self) -> bool:
        return any(
            item.kind == "text" and item.extension in CODE_EXTENSIONS for item in self.attachments
        )

    @property
    def images(self) -> list[ProcessedAttachment]:
        return [item for item in self.attachments if item.kind == "image"]


def supports_vision(model_id: str | None) -> bool:
    if not model_id:
        return False
    lowered = model_id.lower()
    if model_id in KNOWN_VISION_MODELS:
        return True
    return any(
        token in lowered
        for token in (
            "vision",
            "llava",
            "scout",
            "maverick",
            "qwen3",
            "gpt-4o",
            "gemini",
            "grok",
            "pixtral",
            "flash",
        )
    )


def _extension(filename: str) -> str:
    name = (filename or "").rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    if "." not in name:
        return ""
    return "." + name.rsplit(".", 1)[-1].lower()


def _language_for_extension(ext: str) -> str:
    mapping = {
        ".java": "java",
        ".py": "python",
        ".js": "javascript",
        ".ts": "typescript",
        ".md": "markdown",
        ".json": "json",
        ".xml": "xml",
        ".yml": "yaml",
        ".yaml": "yaml",
        ".sql": "sql",
        ".html": "html",
        ".css": "css",
        ".cs": "csharp",
        ".txt": "text",
    }
    return mapping.get(ext, "text")


def _read_limited(file_storage: FileStorage, max_bytes: int) -> bytes:
    raw = file_storage.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise AttachmentError(
            "ATTACHMENT_TOO_LARGE",
            f"Each file must be under {max_bytes // (1024 * 1024)} MB.",
        )
    return raw


def _extract_pdf_text(data: bytes, filename: str) -> tuple[str, int]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover
        raise AttachmentError(
            "PDF_UNSUPPORTED",
            "PDF support is not installed. Run: pip install pypdf",
        ) from exc

    try:
        reader = PdfReader(BytesIO(data))
    except Exception as exc:  # noqa: BLE001
        logger.warning("PDF open failed for %s: %s", filename, type(exc).__name__)
        raise AttachmentError("INVALID_ATTACHMENT", f"Unable to read PDF '{filename}'.") from exc

    pages = reader.pages[:MAX_PDF_PAGES]
    chunks: list[str] = []
    for index, page in enumerate(pages, start=1):
        try:
            page_text = page.extract_text() or ""
        except Exception:  # noqa: BLE001
            page_text = ""
        if page_text.strip():
            chunks.append(f"[Page {index}]\n{page_text.strip()}")

    text = "\n\n".join(chunks).strip()
    if not text:
        raise AttachmentError(
            "INVALID_ATTACHMENT",
            f"No readable text was found in PDF '{filename}'. Scanned image-only PDFs are not supported yet.",
        )
    if len(text) > MAX_PDF_CHARS:
        text = text[:MAX_PDF_CHARS] + "\n\n[PDF text truncated for model context]"
    return text, len(reader.pages)


def process_uploads(files: list[FileStorage]) -> AttachmentBundle:
    """Validate and parse uploaded files into provider-ready attachments."""
    usable = [f for f in files if f and getattr(f, "filename", None)]
    if len(usable) > MAX_FILES:
        raise AttachmentError("TOO_MANY_ATTACHMENTS", f"You can attach at most {MAX_FILES} files.")

    bundle = AttachmentBundle()
    for file_storage in usable:
        filename = (file_storage.filename or "upload").strip() or "upload"
        ext = _extension(filename)
        if ext not in ALLOWED_EXTENSIONS:
            raise AttachmentError(
                "UNSUPPORTED_ATTACHMENT",
                f"Unsupported file type '{ext or filename}'. Allowed: Java, PDF, PNG, JPG, and common text/code files.",
            )

        data = _read_limited(file_storage, MAX_FILE_BYTES)
        if not data:
            raise AttachmentError("INVALID_ATTACHMENT", f"File '{filename}' is empty.")

        mime = file_storage.mimetype or mimetypes.guess_type(filename)[0] or "application/octet-stream"

        if ext in IMAGE_EXTENSIONS:
            if mime not in {"image/png", "image/jpeg", "image/jpg"}:
                mime = "image/png" if ext == ".png" else "image/jpeg"
            # Groq vision rejects images smaller than 2x2.
            try:
                from PIL import Image as PILImage
            except ImportError:
                PILImage = None  # type: ignore[misc, assignment]
            if PILImage is not None:
                try:
                    with PILImage.open(BytesIO(data)) as img:
                        width, height = img.size
                    if width < 2 or height < 2:
                        raise AttachmentError(
                            "INVALID_ATTACHMENT",
                            f"Image '{filename}' is too small ({width}x{height}). Use at least 2x2 pixels.",
                        )
                except AttachmentError:
                    raise
                except Exception:  # noqa: BLE001
                    pass
            encoded = base64.b64encode(data).decode("ascii")
            bundle.attachments.append(
                ProcessedAttachment(
                    filename=filename,
                    kind="image",
                    extension=ext,
                    mime_type=mime,
                    data_url=f"data:{mime};base64,{encoded}",
                )
            )
            continue

        if ext == ".pdf":
            text, page_count = _extract_pdf_text(data, filename)
            bundle.attachments.append(
                ProcessedAttachment(
                    filename=filename,
                    kind="pdf",
                    extension=ext,
                    mime_type="application/pdf",
                    text=text,
                    page_count=page_count,
                )
            )
            continue

        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = data.decode("utf-8", errors="replace")
        text = text.replace("\x00", "")
        if len(text) > MAX_TEXT_CHARS:
            text = text[:MAX_TEXT_CHARS] + "\n\n[File truncated]"
        bundle.attachments.append(
            ProcessedAttachment(
                filename=filename,
                kind="text",
                extension=ext,
                mime_type=mime,
                text=text,
                language=_language_for_extension(ext),
            )
        )

    return bundle


def build_stored_content(user_text: str, bundle: AttachmentBundle) -> str:
    """Content saved in SQLite (text extracts + image labels)."""
    parts: list[str] = []
    cleaned = (user_text or "").strip()
    if cleaned:
        parts.append(cleaned)

    for item in bundle.attachments:
        if item.kind == "image":
            parts.append(f"[Attached image: {item.filename}]")
        elif item.kind == "pdf":
            pages = f" ({item.page_count} pages)" if item.page_count else ""
            parts.append(
                f"--- Attached PDF: {item.filename}{pages} ---\n{item.text}"
            )
        else:
            lang = item.language or "text"
            parts.append(
                f"--- Attached file: {item.filename} ---\n```{lang}\n{item.text}\n```"
            )

    if not parts:
        raise AttachmentError("INVALID_SETTINGS", "Message cannot be empty.")
    return "\n\n".join(parts).strip()


def build_provider_user_content(user_text: str, bundle: AttachmentBundle) -> str | list[dict[str, Any]]:
    """Content sent to the LLM for the current turn."""
    stored = build_stored_content(user_text, bundle)
    if not bundle.has_images:
        return stored

    prompt = (user_text or "").strip()
    if not prompt:
        prompt = "Please analyze the attached image(s) and describe anything important."

    # Keep extracted non-image attachments in the text part.
    text_bits = [prompt]
    for item in bundle.attachments:
        if item.kind == "pdf":
            text_bits.append(f"--- Attached PDF: {item.filename} ---\n{item.text}")
        elif item.kind == "text":
            text_bits.append(
                f"--- Attached file: {item.filename} ---\n```{item.language}\n{item.text}\n```"
            )
        elif item.kind == "image":
            text_bits.append(f"[Attached image: {item.filename}]")

    content: list[dict[str, Any]] = [
        {"type": "text", "text": "\n\n".join(text_bits).strip()}
    ]
    for image in bundle.images:
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": image.data_url},
            }
        )
    return content


def attachment_system_hint(bundle: AttachmentBundle) -> str:
    """Extra system guidance when files are attached on this turn."""
    hints: list[str] = []
    if bundle.has_pdf:
        hints.append(
            "The user attached PDF text extracts. Use the page markers, quote relevant passages, "
            "and answer from the document content when possible."
        )
    if bundle.has_code:
        hints.append(
            "The user attached source code. Review it carefully, preserve identifiers, "
            "point out bugs or improvements, and provide corrected code when asked."
        )
    if bundle.has_images:
        hints.append(
            "The user attached image(s). Describe and analyze what is visible; "
            "do not invent details that are not in the image."
        )
    return " ".join(hints)


def resolve_model_for_attachments(
    requested_model: str,
    bundle: AttachmentBundle,
    provider_id: str,
    vision_fallback: str | None = None,
) -> tuple[str, bool]:
    """Return (model_id, switched_for_attachments)."""
    model = (requested_model or "").strip()
    provider = (provider_id or "").strip().lower()
    switched = False

    if bundle.has_images:
        if not supports_vision(model):
            fallback = (vision_fallback or VISION_FALLBACKS.get(provider) or "").strip()
            if not fallback:
                raise AttachmentError(
                    "MODEL_UNAVAILABLE",
                    f"{provider or 'This provider'} does not support image analysis with the current setup. "
                    "Switch to Groq (vision model), Gemini, or OpenRouter gpt-4o-mini / Grok.",
                )
            model = fallback
            switched = True
        return model, switched

    if bundle.has_pdf:
        preferred = PDF_PREFERRED.get(provider)
        # Keep user's model if set; only fill empty model with a PDF-friendly default.
        if preferred and not model:
            model = preferred
            switched = True
        return model, switched

    if bundle.has_code:
        preferred = CODE_PREFERRED.get(provider)
        if preferred and not model:
            model = preferred
            switched = True
        return model, switched

    return model, False
