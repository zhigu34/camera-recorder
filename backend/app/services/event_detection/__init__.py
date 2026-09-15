from app.services.event_detection.motion_source import LocalMotionEventSource
from app.services.event_detection.registry import EventSourceRegistry


event_source_registry = EventSourceRegistry()
event_source_registry.register(LocalMotionEventSource())

__all__ = ["event_source_registry"]
