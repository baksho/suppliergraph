import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from suppliergraph.llm import LLMUnavailable, OpenAICompatLLM, get_llm

SEEN = {}


class H(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        SEEN.update(path=self.path, auth=self.headers.get("Authorization"), body=body)
        code, out = (500, {"error": "boom"}) if body["messages"][1]["content"] == "fail" else (
            200, {"choices": [{"message": {"content": "SELECT 1"}}]})
        self.send_response(code); self.send_header("Content-Type", "application/json"); self.end_headers()
        self.wfile.write(json.dumps(out).encode())

    def log_message(self, *a):
        pass


@pytest.fixture(scope="module")
def server():
    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}/v1"
    srv.shutdown()


def test_openai_compat_roundtrip(server):
    llm = OpenAICompatLLM(server, "some/model", "tok")
    assert llm.complete("sys", "hello") == "SELECT 1"
    assert SEEN["path"] == "/v1/chat/completions" and SEEN["auth"] == "Bearer tok"
    assert SEEN["body"]["model"] == "some/model" and SEEN["body"]["messages"][0] == {"role": "system", "content": "sys"}


def test_errors_are_llm_unavailable(server):
    with pytest.raises(LLMUnavailable):
        OpenAICompatLLM(server, "m").complete("s", "fail")
    with pytest.raises(LLMUnavailable):
        OpenAICompatLLM("http://127.0.0.1:9/v1", "m", timeout=2).complete("s", "x")
    with pytest.raises(LLMUnavailable):
        OpenAICompatLLM(server, "")


def test_provider_selection(monkeypatch, server):
    for k in ("ANTHROPIC_API_KEY", "HF_TOKEN", "SG_LLM_PROVIDER", "SG_LLM_MODEL", "SG_LLM_BASE_URL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("HF_TOKEN", "hf_x"); monkeypatch.setenv("SG_LLM_MODEL", "m/x")
    llm = get_llm()
    assert isinstance(llm, OpenAICompatLLM) and llm.url.startswith("https://router.huggingface.co/v1")
    monkeypatch.setenv("SG_LLM_PROVIDER", "openai_compat"); monkeypatch.setenv("SG_LLM_BASE_URL", server)
    assert get_llm().url.startswith(server)
    monkeypatch.setenv("SG_LLM_PROVIDER", "nope")
    with pytest.raises(LLMUnavailable):
        get_llm()
