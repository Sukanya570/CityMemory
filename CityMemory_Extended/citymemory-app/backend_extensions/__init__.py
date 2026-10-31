"""Optional CityMemory backend feature registry.

The original Flask API remains the stable core. Add-on blueprints are enabled
here so new features can be developed without rewriting server.py.
"""
from importlib import import_module

ENABLED_BLUEPRINTS = [
    "backend_extensions.features.citizen_portal:bp",
]

def register_all(app):
    for dotted_path in ENABLED_BLUEPRINTS:
        module_path, attribute = dotted_path.split(":", 1)
        module = import_module(module_path)
        blueprint = getattr(module, attribute)
        if hasattr(module, "register"):
            module.register(app)
        app.register_blueprint(blueprint)
