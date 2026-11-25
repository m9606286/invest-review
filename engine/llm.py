"""LLM 呼叫層。Step 2 以 Anthropic Messages API 為預設實作；測試用 ScriptedLLM（tests_step2/mock.py）。"""
import json, os, urllib.request


class LLMError(Exception):
    pass


class AnthropicLLM:
    def __init__(self, api_key=None, models=None, max_tokens=6000, timeout=180):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise LLMError("未設定 ANTHROPIC_API_KEY")
        self.models = models or [os.environ.get("INVEST_PRIMARY_MODEL", "claude-sonnet-5-5"),
                                 os.environ.get("INVEST_BACKUP_MODEL", "claude-haiku-5-5")]
        self.max_tokens, self.timeout = max_tokens, timeout

    def complete(self, system, user, model):
        body = json.dumps({"model": model, "max_tokens": self.max_tokens, "temperature": 0, "system": system,
                           "messages": [{"role": "user", "content": user}]}).encode()
        req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body, method="POST",
                                     headers={"x-api-key": self.api_key, "anthropic-version": "2023-06-01",
                                              "content-type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                data = json.loads(r.read())
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
