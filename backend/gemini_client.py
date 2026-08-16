"""Backward-compatible entry point — kept so existing imports
(`from gemini_client import generate_text, ...`) and this codebase's
existing tests (which monkeypatch attributes on this module) keep working
unchanged. The actual implementation — provider-agnostic, Gemini as
primary with a configurable fallback provider — now lives in
`llm/gateway.py`; see its module docstring for the "Gemini boundary"
architecture and the full provider-routing design.
"""

from llm.base import HEALORA_SYSTEM_INSTRUCTION
from llm.gateway import generate_json, generate_text, is_available

__all__ = ["HEALORA_SYSTEM_INSTRUCTION", "generate_json", "generate_text", "is_available"]
