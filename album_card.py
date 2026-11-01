"""An album tile that turns over to reveal interactive content."""

import math

import cairo
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk


class FlipCard(Gtk.Overlay):
    DURATION = 0.38

    def __init__(self, front, back, size):
        super().__init__()
        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.NONE)
        self.stack.add_named(front, 'front')
        self.stack.add_named(back, 'back')
        self.stack.set_visible_child_name('front')
        self.add(self.stack)
        self.flip_canvas = Gtk.DrawingArea()
        self.flip_canvas.set_halign(Gtk.Align.FILL)
        self.flip_canvas.set_valign(Gtk.Align.FILL)
        self.flip_canvas.set_no_show_all(True)
        self.flip_canvas.connect('draw', self.draw_flip)
        self.add_overlay(self.flip_canvas)
        self.flip_canvas.hide()
        self.animating = False
        self.side = 'front'
        self.surface = None
        self.progress = 0.0
        self.queued_side = None
        self.on_side_shown = None
        self.started_at = None
        self.resize_card(size)

    def resize_card(self, size):
        self.set_size_request(size, size)

    def snapshot(self, widget):
        width = max(1, self.get_allocated_width())
        height = max(1, self.get_allocated_height())
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
        widget.draw(cairo.Context(surface))
        return surface

    def flip(self):
        target = 'front' if (self.target if self.animating else self.side) == 'back' else 'back'
        self.show_side(target)

    def show_side(self, target):
        if self.animating:
            self.queued_side = target if target != self.target else None
            return
        if target == self.side:
            return
        if not self.get_mapped():
            self.side = target
            self.stack.set_visible_child_name(target)
            if self.on_side_shown:
                self.on_side_shown(target)
            return
        self.surface = self.snapshot(self.stack.get_visible_child())
        self.target = target
        self.queued_side = None
        self.swapped = False
        self.back_snapshot_pending = False
        self.progress = 0.0
        self.started_at = None
        self.animating = True
        self.stack.set_opacity(0)
        self.flip_canvas.show()
        self.flip_canvas.queue_draw()
        self.add_tick_callback(self.animate_tick)

    def animate_tick(self, _widget, frame_clock):
        now = frame_clock.get_frame_time()
        if self.started_at is None:
            self.started_at = now
        self.progress = min(1.0, (now - self.started_at) / (self.DURATION * 1000000))
        return self.animate()

    def animate(self):
        if not self.get_mapped():
            if self.get_parent() is not None:
                self.side = self.target
                self.stack.set_visible_child_name(self.target)
                self.stack.set_opacity(1)
                self.flip_canvas.hide()
                if self.on_side_shown:
                    self.on_side_shown(self.side)
            self.surface = None
            self.animating = False
            self.queued_side = None
            return False
        if self.progress >= 0.5 and not self.swapped:
            self.stack.set_visible_child_name(self.target)
            self.swapped = True
            self.back_snapshot_pending = True
        elif self.swapped and self.back_snapshot_pending:
            self.surface = self.snapshot(self.stack.get_visible_child())
            self.back_snapshot_pending = False
        if self.progress >= 1.0:
            self.side = self.target
            self.stack.set_opacity(1)
            self.flip_canvas.hide()
            self.surface = None
            self.animating = False
            queued = self.queued_side
            self.queued_side = None
            if self.on_side_shown:
                self.on_side_shown(self.side)
            if queued and queued != self.side:
                self.show_side(queued)
            return False
        self.flip_canvas.queue_draw()
        return True

    def draw_flip(self, _widget, context):
        if not self.surface:
            return False
        width = self.get_allocated_width()
        scale = max(0.01, abs(math.cos(math.pi * self.progress)))
        context.translate(width / 2, 0)
        context.scale(scale, 1)
        context.translate(-width / 2, 0)
        context.set_source_surface(self.surface, 0, 0)
        context.paint()
        context.set_source_rgba(0, 0, 0, (1 - scale) * 0.28)
        context.paint()
        return False
