from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path
from urllib.error import HTTPError
from typing import Any, Callable


DEFAULT_IMAGE_API_BASE_URL = "http://104.238.220.141:9988"
DEFAULT_IMAGE_API_KEY: str | None = None
DEFAULT_IMAGE_MODEL = "gemini-3.1-flash-image-preview"

PostJson = Callable[[str, dict[str, str], dict[str, Any]], dict[str, Any]]


def _join_openai_path(api_base_url: str, path: str) -> str:
    base = api_base_url.rstrip("/")
    if base.endswith("/v1"):
        return f"{base}{path}"
    return f"{base}/v1{path}"


def post_json(url: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=body, method="POST")
    for key, value in headers.items():
        request.add_header(key, value)
    request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            response_body = response.read().decode("utf-8")
    except HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"POST {url} failed with HTTP {exc.code}: {error_body}") from exc
    return json.loads(response_body)


def _download_url(url: str) -> tuple[bytes, str]:
    with urllib.request.urlopen(url, timeout=120) as response:
        body = response.read()
        content_type = response.headers.get("Content-Type", "")
    ext = mimetypes.guess_extension(content_type.split(";")[0].strip()) or Path(urllib.parse.urlsplit(url).path).suffix
    return body, ext or ".png"


def _decode_image_data(item: dict[str, Any]) -> tuple[bytes, str]:
    b64_value = item.get("b64_json") or item.get("base64") or item.get("image")
    if isinstance(b64_value, str) and b64_value:
        if b64_value.startswith("data:"):
            header, _, encoded = b64_value.partition(",")
            mime = header.split(";", 1)[0].removeprefix("data:")
            ext = mimetypes.guess_extension(mime) or ".png"
            return base64.b64decode(encoded), ext
        return base64.b64decode(b64_value), ".png"

    url = item.get("url")
    if isinstance(url, str) and url:
        return _download_url(url)

    raise ValueError("Image generation response did not contain b64_json, data URL, or URL image data.")


def _decode_gemini_image_data(response: dict[str, Any]) -> tuple[bytes, str]:
    for candidate in response.get("candidates", []):
        for part in candidate.get("content", {}).get("parts", []):
            inline_data = part.get("inlineData") or part.get("inline_data")
            if not isinstance(inline_data, dict):
                continue
            encoded = inline_data.get("data")
            if not isinstance(encoded, str) or not encoded:
                continue
            mime = inline_data.get("mimeType") or inline_data.get("mime_type") or "image/png"
            ext = mimetypes.guess_extension(str(mime)) or ".png"
            return base64.b64decode(encoded), ext
    raise ValueError("Gemini image response did not contain inlineData image data.")


def _gemini_image_payload(model: str, prompt: str, size: str) -> tuple[str, dict[str, Any]]:
    image_size = "1K"
    if size.lower() in {"2k", "2048x2048"}:
        image_size = "2K"
    return (
        f"/v1beta/models/{urllib.parse.quote(model, safe='')}:generateContent",
        {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseModalities": ["TEXT", "IMAGE"],
                "imageConfig": {"aspectRatio": "1:1", "imageSize": image_size},
            },
        },
    )


def _safe_image_id(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    return cleaned.strip("._") or "image"


def generate_task3_images(
    prompt_bundle: dict[str, Any],
    *,
    output_dir: Path,
    api_base_url: str = DEFAULT_IMAGE_API_BASE_URL,
    api_key: str | None = None,
    model: str = DEFAULT_IMAGE_MODEL,
    size: str = "1024x1024",
    api_format: str = "gemini",
    dry_run: bool = False,
    post_json: PostJson = post_json,
) -> list[dict[str, Any]]:
    prompts = prompt_bundle.get("prompts", [])
    if not isinstance(prompts, list):
        raise ValueError("prompt_bundle must contain a list field named 'prompts'.")

    resolved_key = api_key or os.getenv("TASK3_IMAGE_API_KEY")
    image_dir = output_dir / "generated_images"
    image_dir.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, Any]] = []
    for index, prompt_item in enumerate(prompts, start=1):
        prompt_id = _safe_image_id(str(prompt_item.get("id") or f"image_{index}"))
        prompt = str(prompt_item.get("prompt") or "").strip()
        if not prompt:
            raise ValueError(f"Image prompt {prompt_id!r} is empty.")

        if api_format == "openai":
            url = _join_openai_path(api_base_url, "/images/generations")
            payload = {
                "model": model,
                "prompt": prompt,
                "n": 1,
                "size": size,
                "response_format": "b64_json",
            }
        elif api_format == "gemini":
            path, payload = _gemini_image_payload(model, prompt, size)
            url = api_base_url.rstrip("/") + path
        else:
            raise ValueError("api_format must be 'gemini' or 'openai'.")

        if dry_run:
            results.append(
                {
                    "id": prompt_id,
                    "purpose": prompt_item.get("purpose", ""),
                    "prompt": prompt,
                    "status": "planned",
                    "model": model,
                    "api_base_url": api_base_url,
                    "api_format": api_format,
                    "request_url": url,
                    "request_payload": payload,
                    "path": None,
                }
            )
            continue

        if not resolved_key:
            raise ValueError("Image generation requires --image-api-key or TASK3_IMAGE_API_KEY.")
        response = post_json(url, {"Authorization": f"Bearer {resolved_key}"}, payload)
        if api_format == "openai":
            data = response.get("data")
            if not isinstance(data, list) or not data:
                raise ValueError(f"Image generation response for {prompt_id!r} did not contain a non-empty data list.")
            image_bytes, ext = _decode_image_data(data[0])
        else:
            image_bytes, ext = _decode_gemini_image_data(response)
        image_path = image_dir / f"{prompt_id}{ext}"
        image_path.write_bytes(image_bytes)
        results.append(
            {
                "id": prompt_id,
                "purpose": prompt_item.get("purpose", ""),
                "prompt": prompt,
                "status": "generated",
                "model": model,
                "api_base_url": api_base_url,
                "api_format": api_format,
                "request_url": url,
                "path": str(image_path),
            }
        )

    return results
