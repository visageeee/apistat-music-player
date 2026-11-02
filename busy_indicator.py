"""Delayed, reference-counted indicator for foreground background work."""

from gi.repository import GLib


class BusyIndicator:
    def __init__(self, spinner):
        self.spinner = spinner
        self.pending = 0
        self.timer = 0
        self.closed = False

    def begin(self):
        if self.closed:
            return
        self.pending += 1
        if self.pending == 1:
            self.timer = GLib.timeout_add(2000, self._reveal)

    def _reveal(self):
        self.timer = 0
        if self.pending and not self.closed:
            self.spinner.show()
            self.spinner.start()
        return False

    def end(self):
        if not self.pending:
            return
        self.pending -= 1
        if not self.pending:
            if self.timer:
                GLib.source_remove(self.timer)
                self.timer = 0
            self.spinner.stop()
            self.spinner.hide()

    def close(self):
        self.closed = True
        self.pending = 0
        if self.timer:
            GLib.source_remove(self.timer)
            self.timer = 0
        self.spinner.stop()
        self.spinner.hide()
