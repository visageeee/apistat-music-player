#!/usr/bin/env python3
"""Standalone Linux GPU album-wall experiment; does not modify the player."""
import argparse
import ctypes
import glob
import os
import time
from pathlib import Path

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk

GL_TEXTURE_2D = 0x0DE1
GL_RGBA = 0x1908
GL_UNSIGNED_BYTE = 0x1401
GL_TEXTURE_MIN_FILTER = 0x2801
GL_TEXTURE_MAG_FILTER = 0x2800
GL_LINEAR = 0x2601
GL_COLOR_BUFFER_BIT = 0x4000
GL_TRIANGLES = 4
GL_VERTEX_SHADER = 0x8B31
GL_FRAGMENT_SHADER = 0x8B30
GL_COMPILE_STATUS = 0x8B81
GL_LINK_STATUS = 0x8B82
GL_ARRAY_BUFFER = 0x8892
GL_STREAM_DRAW = 0x88E0
GL_FLOAT = 0x1406
GL_RENDERER = 0x1F01


def load_gl():
    gl = ctypes.CDLL('libGL.so.1')
    signatures = {
        'glGetString': (ctypes.c_char_p, [ctypes.c_uint]),
        'glGetError': (ctypes.c_uint, []),
        'glClearColor': (None, [ctypes.c_float] * 4),
        'glClear': (None, [ctypes.c_uint]),
        'glEnable': (None, [ctypes.c_uint]),
        'glViewport': (None, [ctypes.c_int] * 4),
        'glGenTextures': (None, [ctypes.c_int, ctypes.POINTER(ctypes.c_uint)]),
        'glBindTexture': (None, [ctypes.c_uint, ctypes.c_uint]),
        'glTexParameteri': (None, [ctypes.c_uint, ctypes.c_uint, ctypes.c_int]),
        'glTexImage2D': (None, [ctypes.c_uint, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, ctypes.c_uint, ctypes.c_uint,
                                ctypes.c_void_p]),
        'glCreateShader': (ctypes.c_uint, [ctypes.c_uint]),
        'glShaderSource': (None, [ctypes.c_uint, ctypes.c_int, ctypes.POINTER(ctypes.c_char_p), ctypes.c_void_p]),
        'glCompileShader': (None, [ctypes.c_uint]),
        'glGetShaderiv': (None, [ctypes.c_uint, ctypes.c_uint, ctypes.POINTER(ctypes.c_int)]),
        'glGetShaderInfoLog': (None, [ctypes.c_uint, ctypes.c_int, ctypes.c_void_p, ctypes.c_char_p]),
        'glDeleteShader': (None, [ctypes.c_uint]),
        'glCreateProgram': (ctypes.c_uint, []),
        'glAttachShader': (None, [ctypes.c_uint, ctypes.c_uint]),
        'glBindAttribLocation': (None, [ctypes.c_uint, ctypes.c_uint, ctypes.c_char_p]),
        'glLinkProgram': (None, [ctypes.c_uint]),
        'glGetProgramiv': (None, [ctypes.c_uint, ctypes.c_uint, ctypes.POINTER(ctypes.c_int)]),
        'glGetProgramInfoLog': (None, [ctypes.c_uint, ctypes.c_int, ctypes.c_void_p, ctypes.c_char_p]),
        'glUseProgram': (None, [ctypes.c_uint]),
        'glDeleteProgram': (None, [ctypes.c_uint]),
        'glGenVertexArrays': (None, [ctypes.c_int, ctypes.POINTER(ctypes.c_uint)]),
        'glBindVertexArray': (None, [ctypes.c_uint]),
        'glDeleteVertexArrays': (None, [ctypes.c_int, ctypes.POINTER(ctypes.c_uint)]),
        'glGenBuffers': (None, [ctypes.c_int, ctypes.POINTER(ctypes.c_uint)]),
        'glBindBuffer': (None, [ctypes.c_uint, ctypes.c_uint]),
        'glBufferData': (None, [ctypes.c_uint, ctypes.c_ssize_t, ctypes.c_void_p, ctypes.c_uint]),
        'glDeleteBuffers': (None, [ctypes.c_int, ctypes.POINTER(ctypes.c_uint)]),
        'glEnableVertexAttribArray': (None, [ctypes.c_uint]),
        'glVertexAttribPointer': (None, [ctypes.c_uint, ctypes.c_int, ctypes.c_uint,
                                         ctypes.c_ubyte, ctypes.c_int, ctypes.c_void_p]),
        'glDrawArrays': (None, [ctypes.c_uint, ctypes.c_int, ctypes.c_int]),
        'glReadPixels': (None, [ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p]),
        'glDeleteTextures': (None, [ctypes.c_int, ctypes.POINTER(ctypes.c_uint)]),
    }
    for name, (result, args) in signatures.items():
        fn = getattr(gl, name)
        fn.restype, fn.argtypes = result, args
    return gl


def atlas_from_files(paths, cell=128, columns=16):
    """Pack square thumbnails into RGBA pixels for one GPU upload."""
    images = []
    for path in paths:
        try:
            image = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(path), cell, cell, False)
            if not image.get_has_alpha():
                image = image.add_alpha(False, 0, 0, 0)
            images.append(image)
        except GLib.Error:
            continue
    rows = max(1, (len(images) + columns - 1) // columns)
    width, height = columns * cell, rows * cell
    pixels = bytearray(width * height * 4)
    for index, image in enumerate(images):
        source = image.get_pixels()
        x, y = index % columns * cell, index // columns * cell
        for row in range(cell):
            start = row * image.get_rowstride()
            target = ((y + row) * width + x) * 4
            pixels[target:target + cell * 4] = source[start:start + cell * 4]
    return width, height, pixels, len(images)


class Probe(Gtk.Window):
    def __init__(self, atlas, self_test=False):
        super().__init__(title='Apistat GPU album wall experiment')
        self.set_default_size(1100, 700)
        self.connect('destroy', Gtk.main_quit)
        self.atlas = atlas
        self.gl = load_gl()
        self.texture = ctypes.c_uint()
        self.vao, self.buffer, self.program = ctypes.c_uint(), ctypes.c_uint(), 0
        self.zoom = 160
        self.offset = 0
        self.frames = 0
        self.resize_steps = 0
        self.self_test = self_test
        self.non_background = False
        self.failure = False
        self.start = time.monotonic()
        self.area = Gtk.GLArea()
        self.area.connect('realize', self.realize_gl)
        self.area.connect('unrealize', self.unrealize_gl)
        self.area.connect('render', self.render)
        self.area.add_events(Gdk.EventMask.SCROLL_MASK | Gdk.EventMask.SMOOTH_SCROLL_MASK)
        self.area.connect('scroll-event', self.scroll)
        self.add(self.area)

    def realize_gl(self, area):
        area.make_current()
        if area.get_error():
            print('OpenGL context failed:', area.get_error(), flush=True)
            self.failure = True
            GLib.idle_add(Gtk.main_quit)
            return
        if area.get_context().get_use_es():
            print('OpenGL ES is not supported by this prototype.', flush=True)
            self.failure = True
            GLib.idle_add(Gtk.main_quit)
            return
        gl = self.gl
        try:
            self.setup_program()
        except RuntimeError as error:
            print('OpenGL shader setup failed:', error, flush=True)
            self.failure = True
            GLib.idle_add(Gtk.main_quit)
            return
        print('OpenGL renderer:', (gl.glGetString(GL_RENDERER) or b'unknown').decode(), flush=True)
        width, height, pixels, count = self.atlas
        gl.glGenTextures(1, ctypes.byref(self.texture))
        gl.glBindTexture(GL_TEXTURE_2D, self.texture)
        gl.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
        gl.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
        data = (ctypes.c_ubyte * len(pixels)).from_buffer(pixels)
        gl.glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, width, height, 0,
                        GL_RGBA, GL_UNSIGNED_BYTE, data)
        print(f'Atlas: {count} covers, {width} × {height}; GL error {gl.glGetError()}', flush=True)
        if self.self_test:
            GLib.timeout_add(30, self.test_resize)

    def setup_program(self):
        gl = self.gl
        def compile_shader(kind, source):
            shader = gl.glCreateShader(kind)
            data = ctypes.c_char_p(source)
            gl.glShaderSource(shader, 1, ctypes.byref(data), None)
            gl.glCompileShader(shader)
            status = ctypes.c_int()
            gl.glGetShaderiv(shader, GL_COMPILE_STATUS, ctypes.byref(status))
            if not status.value:
                message = ctypes.create_string_buffer(2048)
                gl.glGetShaderInfoLog(shader, len(message), None, message)
                gl.glDeleteShader(shader)
                raise RuntimeError(message.value.decode(errors='replace'))
            return shader
        vertex = compile_shader(GL_VERTEX_SHADER, b"""#version 150
in vec2 position; in vec2 texcoord; out vec2 uv;
void main() { uv = texcoord; gl_Position = vec4(position, 0.0, 1.0); }
""")
        fragment = compile_shader(GL_FRAGMENT_SHADER, b"""#version 150
uniform sampler2D image; in vec2 uv; out vec4 color;
void main() { color = texture(image, uv); }
""")
        program = gl.glCreateProgram()
        gl.glAttachShader(program, vertex)
        gl.glAttachShader(program, fragment)
        gl.glBindAttribLocation(program, 0, b'position')
        gl.glBindAttribLocation(program, 1, b'texcoord')
        gl.glLinkProgram(program)
        gl.glDeleteShader(vertex)
        gl.glDeleteShader(fragment)
        status = ctypes.c_int()
        gl.glGetProgramiv(program, GL_LINK_STATUS, ctypes.byref(status))
        if not status.value:
            message = ctypes.create_string_buffer(2048)
            gl.glGetProgramInfoLog(program, len(message), None, message)
            gl.glDeleteProgram(program)
            raise RuntimeError(message.value.decode(errors='replace'))
        self.program = program
        gl.glGenVertexArrays(1, ctypes.byref(self.vao))
        gl.glGenBuffers(1, ctypes.byref(self.buffer))
        gl.glBindVertexArray(self.vao)
        gl.glBindBuffer(GL_ARRAY_BUFFER, self.buffer)
        gl.glEnableVertexAttribArray(0)
        gl.glEnableVertexAttribArray(1)
        gl.glVertexAttribPointer(0, 2, GL_FLOAT, 0, 16, None)
        gl.glVertexAttribPointer(1, 2, GL_FLOAT, 0, 16, ctypes.c_void_p(8))

    def test_resize(self):
        if self.resize_steps >= 20:
            return self.finish_test()
        self.resize_steps += 1
        self.resize(900 + self.resize_steps * 10, 620 + self.resize_steps * 3)
        self.area.queue_render()
        return True

    def unrealize_gl(self, area):
        area.make_current()
        if not area.get_error() and self.texture.value:
            self.gl.glDeleteTextures(1, ctypes.byref(self.texture))
            self.gl.glDeleteBuffers(1, ctypes.byref(self.buffer))
            self.gl.glDeleteVertexArrays(1, ctypes.byref(self.vao))
            self.gl.glDeleteProgram(self.program)

    def render(self, area, _context):
        gl = self.gl
        width, height = area.get_allocated_width(), area.get_allocated_height()
        scale = area.get_scale_factor()
        gl.glViewport(0, 0, width * scale, height * scale)
        gl.glClearColor(0.035, 0.035, 0.035, 1)
        gl.glClear(GL_COLOR_BUFFER_BIT)
        gl.glBindTexture(GL_TEXTURE_2D, self.texture)
        columns = max(1, (width - 40) // (self.zoom + 24))
        row_height = self.zoom + 24
        count = self.atlas[3]
        first = max(0, int(self.offset // row_height))
        last = min((count + columns - 1) // columns, int((self.offset + height) // row_height) + 1)
        atlas_w, atlas_h = self.atlas[:2]
        cell = 128
        vertices = []
        for index in range(first * columns, min(count, last * columns)):
            col, row = index % columns, index // columns
            x = 20 + col * (self.zoom + 24)
            y = 20 + row * row_height - self.offset
            left, right = 2 * x / width - 1, 2 * (x + self.zoom) / width - 1
            top, bottom = 1 - 2 * y / height, 1 - 2 * (y + self.zoom) / height
            u = (index % 16) * cell / atlas_w
            v = (index // 16) * cell / atlas_h
            du, dv = cell / atlas_w, cell / atlas_h
            a = (left, top, u, v)
            b = (right, top, u + du, v)
            c = (right, bottom, u + du, v + dv)
            d = (left, bottom, u, v + dv)
            for vertex in (a, b, c, a, c, d):
                vertices.extend(vertex)
        data = (ctypes.c_float * len(vertices))(*vertices)
        gl.glUseProgram(self.program)
        gl.glBindVertexArray(self.vao)
        gl.glBindBuffer(GL_ARRAY_BUFFER, self.buffer)
        gl.glBufferData(GL_ARRAY_BUFFER, ctypes.sizeof(data), data, GL_STREAM_DRAW)
        gl.glDrawArrays(GL_TRIANGLES, 0, len(vertices) // 4)
        if self.self_test and not self.frames:
            sample = (ctypes.c_ubyte * (100 * 100 * 4))()
            gl.glReadPixels(20 * scale, max(0, (height - 120) * scale), 100, 100,
                            GL_RGBA, GL_UNSIGNED_BYTE, sample)
            self.non_background = any(abs(sample[i] - 9) > 5 or
                                      abs(sample[i + 1] - 9) > 5 or
                                      abs(sample[i + 2] - 9) > 5
                                      for i in range(0, len(sample), 4))
        self.frames += 1
        return True

    def scroll(self, _area, event):
        if event.direction == Gdk.ScrollDirection.SMOOTH:
            ok, _x, delta = event.get_scroll_deltas()
            delta = delta if ok else 0
        else:
            delta = -1 if event.direction == Gdk.ScrollDirection.UP else 1
        if event.state & Gdk.ModifierType.CONTROL_MASK:
            self.zoom = max(64, min(320, self.zoom - int(delta * 16)))
        else:
            width = self.area.get_allocated_width()
            columns = max(1, (width - 40) // (self.zoom + 24))
            rows = (self.atlas[3] + columns - 1) // columns
            maximum = max(0, rows * (self.zoom + 24) + 40 - self.area.get_allocated_height())
            self.offset = max(0, min(maximum, self.offset + delta * 100))
        self.area.queue_render()
        return True

    def finish_test(self):
        self.area.make_current()
        error = self.gl.glGetError()
        self.failure = bool(error or self.frames < 2 or not self.non_background)
        print(f'Rendered {self.frames} frame(s); GL error {error}; '
              f'artwork pixels present: {self.non_background}; '
              f'{self.resize_steps} resize requests', flush=True)
        Gtk.main_quit()
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('--cache', default=str(Path(GLib.get_user_cache_dir()) / 'plex-music-prototype'))
    args = parser.parse_args()
    paths = glob.glob(str(Path(args.cache) / '*' / 'art' / '*.img'))[:256]
    if not paths:
        parser.error('No cached album artwork found. Open Apistat and load some albums first.')
    atlas = atlas_from_files(paths)
    if not atlas[3]:
        parser.error('No readable cached album artwork found.')
    window = Probe(atlas, args.self_test)
    window.show_all()
    Gtk.main()
    if window.failure:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
