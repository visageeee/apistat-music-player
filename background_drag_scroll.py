"""Scroll a view by dragging a non-interactive part of its background."""
import gi

gi.require_version('Gdk', '3.0')
gi.require_version('Gtk', '3.0')
from gi.repository import Gdk, Gtk


class BackgroundDragScroller:
    def __init__(self, adjustment):
        self.adjustment = adjustment
        self.start = None

    def press(self, event):
        if event.button != 1 or event.state & (Gdk.ModifierType.SHIFT_MASK |
                                                Gdk.ModifierType.CONTROL_MASK |
                                                Gdk.ModifierType.MOD1_MASK):
            return False
        if self.adjustment.get_upper() - self.adjustment.get_page_size() <= self.adjustment.get_lower():
            return False
        self.start = (event.y_root, self.adjustment.get_value())
        return True

    def motion(self, event):
        if self.start is None:
            return False
        if not event.state & Gdk.ModifierType.BUTTON1_MASK:
            self.start = None
            return False
        low = self.adjustment.get_lower()
        high = max(low, self.adjustment.get_upper() - self.adjustment.get_page_size())
        self.adjustment.set_value(max(low, min(high, self.start[1] + self.start[0] - event.y_root)))
        return True

    def release(self, event):
        if event.button != 1 or self.start is None:
            return False
        self.start = None
        return True


def attach_background_drag(window):
    """Attach to blank GTK backgrounds while leaving controls and rows alone."""
    controller = BackgroundDragScroller(window.get_vadjustment())
    blocked = (Gtk.Button, Gtk.Entry, Gtk.TextView, Gtk.TreeView, Gtk.Range,
               Gtk.ComboBox, Gtk.ListBox, Gtk.FlowBoxChild, Gtk.EventBox)
    window.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK |
                      Gdk.EventMask.POINTER_MOTION_MASK)
    def pressed(_widget, event):
        widget = Gtk.get_event_widget(event)
        while widget is not None and widget is not window:
            if isinstance(widget, blocked):
                return False
            widget = widget.get_parent()
        return widget is window and controller.press(event)
    window.connect('button-press-event', pressed)
    window.connect('motion-notify-event', lambda _widget, event: controller.motion(event))
    window.connect('button-release-event', lambda _widget, event: controller.release(event))
    return controller
