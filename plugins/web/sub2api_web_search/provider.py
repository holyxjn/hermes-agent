from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List

from agent.web_search_provider import WebSearchProvider

logger = logging.getLogger(__name__)


def _read_model_config() -> Dict[str, Any]:
    try:
        from hermes_cli.config import load_config

        model = load_config().get("model", {})
        return model if isinstance(model, dict) else {}
    except Exception:
        return {}


def _read_dotenv_value(name: str) -> str:
    env_path = Path.home() / ".hermes" / ".env"
    if not env_path.exists():
        return ""
    prefix = f"{name}="
    for raw in env_path.read_text(errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or not line.startswith(prefix):
            continue
        value = line[len(prefix):].strip()
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]
        return value
    return ""


def _strip_code_fence(text: str) -> str:
    clean = text.strip()
    if clean.startswith("```"):
        clean = re.sub(r"^```(?:json)?\s*", "", clean, flags=re.IGNORECASE)
        clean = re.sub(r"\s*```$", "", clean)
    return clean.strip()


def _extract_output_text(payload: Dict[str, Any]) -> str:
    output_text = payload.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    parts: List[str] = []
    for item in payload.get("output", []) or []:
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []) or []:
            if isinstance(content, dict):
                text = content.get("text")
                if isinstance(text, str) and text:
                    parts.append(text)
    return "\n".join(parts).strip()


def _parse_results(text: str, limit: int) -> List[Dict[str, str]]:
    clean = _strip_code_fence(text)
    try:
        data = json.loads(clean)
    except Exception:
        logger.debug("Sub2API web search returned non-JSON text: %s", text[:500])
        return [
            {
                "title": "Search result summary",
                "url": "",
                "description": clean[:1000],
            }
        ] if clean else []

    raw_results = data.get("results", data if isinstance(data, list) else [])
    if not isinstance(raw_results, list):
        return []

    results: List[Dict[str, str]] = []
    for item in raw_results[:limit]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or item.get("name") or "").strip()
        url = str(item.get("url") or item.get("link") or "").strip()
        description = str(
            item.get("description")
            or item.get("snippet")
            or item.get("content")
            or item.get("summary")
            or ""
        ).strip()
        if title or url or description:
            results.append(
                {
                    "title": title,
                    "url": url,
                    "description": description,
                }
            )
    return results


class Sub2APIWebSearchProvider(WebSearchProvider):
    @property
    def name(self) -> str:
        return "sub2api-web-search"

    @property
    def display_name(self) -> str:
        return "Sub2API Web Search"

    def is_available(self) -> bool:
        model = _read_model_config()
        base_url = (
            os.getenv("SUB2API_WEB_SEARCH_BASE_URL")
            or str(model.get("base_url") or "")
        ).strip()
        api_key = (
            os.getenv("SUB2API_WEB_SEARCH_API_KEY")
            or os.getenv("OPENAI_API_KEY")
            or str(model.get("api_key") or "")
            or _read_dotenv_value("OPENAI_API_KEY")
        ).strip()
        return bool(base_url and api_key)

    def supports_search(self) -> bool:
        return True

    def supports_extract(self) -> bool:
        return False

    def search(self, query: str, limit: int = 5) -> Dict[str, Any]:
        import httpx

        limit = max(1, min(int(limit or 5), 10))
        model_cfg = _read_model_config()
        base_url = (
            os.getenv("SUB2API_WEB_SEARCH_BASE_URL")
            or str(model_cfg.get("base_url") or "")
        ).strip().rstrip("/")
        api_key = (
            os.getenv("SUB2API_WEB_SEARCH_API_KEY")
            or os.getenv("OPENAI_API_KEY")
            or str(model_cfg.get("api_key") or "")
            or _read_dotenv_value("OPENAI_API_KEY")
        ).strip()
        model = (
            os.getenv("SUB2API_WEB_SEARCH_MODEL")
            or str(model_cfg.get("default") or "")
            or "gpt-5.5"
        ).strip()

        if not base_url:
            return {"success": False, "error": "Sub2API web search base_url is not configured"}
        if not api_key:
            return {"success": False, "error": "OPENAI_API_KEY is not configured"}

        prompt = (
            f"Search the web for: {query}\n"
            f"Return only valid JSON, no markdown, exactly as "
            f'{{"results":[{{"title":string,"url":string,"description":string}}]}}. '
            f"Include up to {limit} results."
        )
        payload = {
            "model": model,
            "instructions": (
                "You are a web search adapter. You must use the web_search tool "
                "and return only valid JSON."
            ),
            "input": prompt,
            "tools": [{"type": "web_search"}],
            "tool_choice": "auto",
            "max_output_tokens": 800,
        }

        try:
            response = httpx.post(
                f"{base_url}/responses",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=60,
            )
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as exc:
            logger.warning("Sub2API web search HTTP error: %s", exc)
            return {
                "success": False,
                "error": f"Sub2API web search returned HTTP {exc.response.status_code}",
            }
        except Exception as exc:
            logger.warning("Sub2API web search request failed: %s", exc)
            return {"success": False, "error": f"Sub2API web search failed: {exc}"}

        tool_usage = data.get("tool_usage") if isinstance(data, dict) else {}
        web_usage = tool_usage.get("web_search", {}) if isinstance(tool_usage, dict) else {}
        if isinstance(web_usage, dict) and int(web_usage.get("num_requests") or 0) < 1:
            logger.warning("Sub2API web_search response did not report web_search usage")

        text = _extract_output_text(data)
        results = _parse_results(text, limit)
        web_results = [
            {
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "description": item.get("description", ""),
                "position": index + 1,
            }
            for index, item in enumerate(results[:limit])
        ]

        return {"success": True, "data": {"web": web_results}}

    def get_setup_schema(self) -> Dict[str, Any]:
        return {
            "name": "Sub2API Web Search",
            "badge": "custom",
            "tag": "Uses your OpenAI-compatible /responses endpoint with type=web_search.",
            "env_vars": [],
        }
