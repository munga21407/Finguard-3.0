"""Provider-agnostic LLM layer for the intelligence domain.

``base.BaseLLMClient`` is the swap-in interface; ``gemini.GeminiLLMClient`` is the
current implementation.  ``pricing`` and ``telemetry`` are provider-neutral and
shared across implementations.  The legacy ``llm_client`` module re-exports this
package's public surface so existing call sites keep working unchanged.
"""
