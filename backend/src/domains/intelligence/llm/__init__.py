"""Provider-agnostic LLM layer for the intelligence domain.

``base.BaseLLMClient`` is the swap-in interface. ``openai_compat`` is the sole
vendor-SDK importer; ``provider`` wraps it with resilience/telemetry policy;
``failover`` composes a primary + backup provider. ``pricing`` and ``telemetry``
are provider-neutral and shared. The ``llm_client`` module re-exports this
package's public surface so existing call sites keep working unchanged.
"""
