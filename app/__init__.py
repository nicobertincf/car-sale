"""Paquete base del proyecto multiagentes."""

# Compatibility shim for environments with a partial `langchain` package.
try:
    import langchain  # type: ignore

    # langchain_core (0.3.x) still checks legacy globals on `langchain`.
    # Some environments expose a partial `langchain` package without these attrs.
    if not hasattr(langchain, "debug"):
        langchain.debug = False
    if not hasattr(langchain, "verbose"):
        langchain.verbose = False
    if not hasattr(langchain, "llm_cache"):
        langchain.llm_cache = None
except Exception:
    pass
