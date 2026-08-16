"""Shared contract every LLM provider implements.

Not a strict ABC — duck-typed, matching the rest of this codebase's style
— but documented here as the interface llm/gateway.py depends on instead
of any specific vendor SDK:

    is_configured() -> bool
        Cheap, no-network check: does this provider have the credentials
        it needs? The gateway skips a provider entirely (never attempts a
        call, never logs a failure) when this is False.

    generate_text(prompt, system_instruction, temperature) -> str
        Returns the model's text response. Raises ProviderError — never
        returns None or an empty string to signal failure — so the
        gateway can tell "the model said nothing useful" apart from
        "the call succeeded with real content" unambiguously.

    generate_json(prompt, system_instruction, temperature) -> dict
        Same contract, parsed as JSON. Raises ProviderError (reason=
        "invalid_response") if the response isn't valid JSON — shape
        validation against a caller-supplied `validator` happens one
        level up, in the gateway, so every provider is held to the same
        check.

Providers never see or apply a `fallback` value themselves — that's the
gateway's job (see llm/gateway.py's module docstring), so a provider
raising ProviderError always means "try the next thing," never "return
this default text."
"""

# Applied to every provider by default, unless a caller passes its own
# (more specific) system_instruction — see orchestrator.py's several
# purpose-built instructions (contextual follow-ups, pregnancy, open
# conversation). Provider-agnostic on purpose: both Gemini and any
# fallback provider receive the exact same safety rules, so medical
# behavior doesn't depend on which one happened to answer.
HEALORA_SYSTEM_INSTRUCTION = (
    "You are the language layer for Healora, an educational symptom-support "
    "assistant. You are NOT a doctor and this is NOT a diagnostic tool. "
    "Hard rules, no exceptions:\n"
    "1. Never state or imply a definitive diagnosis. Use language like "
    "'possible conditions to discuss with a doctor', never 'you have X'.\n"
    "2. Never invent a disease, symptom, treatment, or medication dosage "
    "that wasn't given to you in the prompt's data. If you weren't given "
    "structured facts about something, say you don't have verified "
    "information rather than filling the gap. Never mention a condition "
    "name that wasn't explicitly provided to you in the prompt.\n"
    "3. Never override or soften an emergency warning — if the app already "
    "flagged something as an emergency, that decision is final and not "
    "yours to reassess.\n"
    "4. Always keep or reinforce the message that this is educational "
    "guidance and a licensed healthcare professional should be consulted, "
    "especially for anything severe, persistent, or worsening.\n"
    "5. Be warm and clear, but concise — this is a chat widget, not an "
    "article."
)

# The reasons the gateway logs and reacts to (see gateway.py's routing
# rules). Not a hard enum — providers pass any short lowercase string —
# but every provider implementation in this package sticks to this set so
# the gateway's retry logic (one retry for "timeout", immediate fallback
# for everything else) stays meaningful.
REASON_QUOTA = "quota"
REASON_RATE_LIMIT = "rate_limit"
REASON_TIMEOUT = "timeout"
REASON_API_ERROR = "api_error"
REASON_INVALID_RESPONSE = "invalid_response"
REASON_UNAVAILABLE = "unavailable"


class ProviderError(Exception):
    """Raised by a provider's generate_text/generate_json when the call
    failed in a way the gateway should potentially route around. Carries a
    classified `reason` (see the REASON_* constants above) that the
    gateway logs and reacts to — never the raw exception message, which
    could in principle echo back request details; callers of this
    exception should treat `str(error)` as safe-to-log context, not as
    something ever shown to an end user.
    """

    def __init__(self, reason, detail=None):
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}" if detail else reason)
