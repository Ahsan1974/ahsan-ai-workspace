"""Attachment parsing tests (no live Groq calls)."""

from __future__ import annotations

from io import BytesIO

from werkzeug.datastructures import FileStorage

from services.attachment_service import (
    build_stored_content,
    process_uploads,
    resolve_model_for_attachments,
    supports_vision,
)


def test_process_java_file():
    data = b"public class Hello {\n  public static void main(String[] args) {}\n}\n"
    upload = FileStorage(stream=BytesIO(data), filename="Hello.java", content_type="text/x-java-source")
    bundle = process_uploads([upload])
    assert len(bundle.attachments) == 1
    assert bundle.attachments[0].kind == "text"
    assert "public class Hello" in bundle.attachments[0].text
    stored = build_stored_content("Review this", bundle)
    assert "Hello.java" in stored
    assert "```java" in stored


def test_process_png_image_builds_data_url():
    # Minimal 1x1 PNG
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
        b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    upload = FileStorage(stream=BytesIO(png), filename="dot.png", content_type="image/png")
    bundle = process_uploads([upload])
    assert bundle.has_images
    assert bundle.images[0].data_url.startswith("data:image/png;base64,")


def test_vision_model_switch():
    from services.attachment_service import AttachmentBundle, ProcessedAttachment

    bundle = AttachmentBundle(
        attachments=[
            ProcessedAttachment(
                filename="a.png",
                kind="image",
                extension=".png",
                mime_type="image/png",
                data_url="data:image/png;base64,xx",
            )
        ]
    )
    model, switched = resolve_model_for_attachments(
        "llama-3.3-70b-versatile",
        bundle,
        "groq",
        vision_fallback="qwen/qwen3.6-27b",
    )
    assert switched is True
    assert model == "qwen/qwen3.6-27b"
    assert supports_vision("qwen/qwen3.6-27b") is True
