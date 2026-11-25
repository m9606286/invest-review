"""LLM 呼叫層：支援 Gemini（免費額度）、OpenAI 相容免費端點與 Anthropic。"""
import json
import os
import urllib.request

from google import genai
from google.genai import types


class LLMError(Exception):
    pass


class GeminiLLM:
    def __init__(self, api_key=None, models=None, max_tokens=8192, timeout=180):
        self.api_key = (api_key or os.environ.get("GEMINI_API_KEY") or "").strip()
        if not self.api_key:
            raise LLMError("未設定 GEMINI_API_KEY（請在介面輸入或設定環境變數）")
        primary = os.environ.get("GEMINI_PRIMARY_MODEL", "gemini-3-flash-preview")
        backup = os.environ.get("GEMINI_BACKUP_MODEL", primary)
        self.models = models or [primary, backup]
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.client = genai.Client(api_key=self.api_key)

    def complete(self, system, user, model):
        try:
            resp = self.client.models.generate_content(
                model=model,
                contents=user,
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    temperature=0,
                    max_output_tokens=self.max_tokens,
                ),
            )
            return resp.text or ""
        except Exception as e:
            raise LLMError(f"Gemini API 呼叫失敗（{model}）：{e}")


class OpenAICompatLLM:
    def __init__(self, api_key=None, base_url=None, model=None, max_tokens=6000, timeout=180):
        self.api_key = (api_key or os.environ.get("OPENAI_COMPAT_API_KEY") or "").strip()
        self.base_url = (base_url or os.environ.get("OPENAI_COMPAT_BASE_URL") or "https://openrouter.ai/api/v1").rstrip("/")
        if not self.api_key:
            raise LLMError("未設定免費 API Key")
        primary = model or os.environ.get("OPENAI_COMPAT_MODEL", "openrouter/free")
        self.models = [primary, primary]
        self.max_tokens = max_tokens
        self.timeout = timeout

    def complete(self, system, user, model):
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": model,
            "temperature": 0,
            "max_tokens": self.max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                data = json.loads(r.read().decode("utf-8"))
        except Exception as e:
            raise LLMError(f"OpenAI 相容 API 呼叫失敗（{model}）：{e}")
        choices = data.get("choices") or []
        if not choices:
            raise LLMError("API 回應中缺少 choices")
        return (choices[0].get("message") or {}).get("content") or ""


class AnthropicLLM:
    def __init__(self, api_key=None, models=None, max_tokens=6000, timeout=180):
        self.api_key = (api_key or os.environ.get("ANTHROPIC_API_KEY") or "").strip()
        if not self.api_key:
            raise LLMError("未設定 ANTHROPIC_API_KEY")
        self.models = models or [
            os.environ.get("INVEST_PRIMARY_MODEL", "claude-sonnet-5-5"),
            os.environ.get("INVEST_BACKUP_MODEL", "claude-haiku-5-5"),
        ]
        self.max_tokens, self.timeout = max_tokens, timeout

    def complete(self, system, user, model):
        body = json.dumps({
            "model": model,
            "max_tokens": self.max_tokens,
            "temperature": 0,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=body,
            method="POST",
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                data = json.loads(r.read().decode("utf-8"))
        except Exception as e:
            raise LLMError(f"API 呼叫失敗：{e}")
        return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")


def extract_json(text):
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t
        t = t.rsplit("```", 1)[0]
    i, j = t.find("{"), t.rfind("}")
    if i < 0 or j <= i:
        raise ValueError("輸出中找不到 JSON 物件")
    return json.loads(t[i:j + 1])
