"""Explicit production ASGI factory; there is intentionally no development fallback."""
import importlib
import os
from .production import ProductionComposition, ProductionStartupError

def create():
    target = os.getenv("JMORAIS_PRODUCTION_COMPOSITION_FACTORY", "")
    if ":" not in target: raise ProductionStartupError("explicit external production composition factory is required")
    module_name, callable_name = target.split(":", 1)
    factory = getattr(importlib.import_module(module_name), callable_name, None)
    if not callable(factory): raise ProductionStartupError("production composition factory is invalid")
    composition = factory()
    if not isinstance(composition, ProductionComposition): raise ProductionStartupError("factory did not return canonical ProductionComposition")
    directory = os.getenv("JMORAIS_WEB_DIST", "")
    if directory:
        from .pilot_static import attach_workspace
        try:
            attach_workspace(composition.app, directory)
        except Exception:
            composition.shutdown()
            raise
    return composition.app
