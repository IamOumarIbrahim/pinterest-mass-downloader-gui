"""UI Controller/Presenter bridging QueueManager events to Tkinter main thread."""

import queue
from typing import Callable, Optional

from pinterest_mass_downloader.application.events import AppEvent
from pinterest_mass_downloader.application.queue_manager import QueueManager
from pinterest_mass_downloader.services.pinterest_adapter import PinterestDLAdapter


class UIController:
    """Presenter connecting QueueManager events safely to the Tkinter UI polling loop."""

    def __init__(self, queue_manager: Optional[QueueManager] = None):
        self.adapter = PinterestDLAdapter()
        self.queue_manager = queue_manager or QueueManager(adapter=self.adapter)
        self.event_queue: queue.Queue = queue.Queue()

        # Subscribe to QueueManager events
        self.queue_manager.subscribe(self._on_event)

    def _on_event(self, event: AppEvent) -> None:
        """Receive thread-safe event from engine/worker and queue for UI main thread."""
        self.event_queue.put(event)

    def process_events(self, handler: Callable[[AppEvent], None]) -> None:
        """Drain event queue and deliver to UI handler (called on Tk main thread)."""
        while not self.event_queue.empty():
            try:
                evt = self.event_queue.get_nowait()
                handler(evt)
            except queue.Empty:
                break
