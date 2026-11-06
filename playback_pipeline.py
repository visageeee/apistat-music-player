"""Serialize potentially blocking GStreamer state transitions off the GTK thread."""
from concurrent.futures import ThreadPoolExecutor
import threading


class PlaybackPipeline:
    def __init__(self, pipeline, on_error=None):
        self.pipeline = pipeline
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='playback-state')
        self.lock = threading.Lock()
        self.pending = 0
        self.closed = False
        self.on_error = on_error

    def busy(self):
        with self.lock:
            return self.pending > 0

    def submit(self, operation, valid=lambda: True):
        with self.lock:
            if self.closed:
                return False
            self.pending += 1
        def run():
            try:
                if valid():
                    operation()
            except Exception:
                if self.on_error is not None and valid():
                    self.on_error()
            finally:
                with self.lock:
                    self.pending -= 1
        try:
            self.executor.submit(run)
            return True
        except RuntimeError:
            with self.lock:
                self.pending -= 1
            return False

    def set_state(self, state, valid=lambda: True):
        return self.submit(lambda: self.pipeline.set_state(state), valid)

    def open(self, uri, state, valid=lambda: True):
        def run():
            self.pipeline.set_property('uri', uri)
            self.pipeline.set_state(state)
        return self.submit(run, valid)

    def shutdown(self, null_state):
        self.set_state(null_state)
        with self.lock:
            self.closed = True
        self.executor.shutdown(wait=False)
