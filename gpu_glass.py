"""Small GPU framebuffer used to blur album-wall backdrops for GTK bars."""
import ctypes

import cairo
from gpu_gl import (GL_ARRAY_BUFFER, GL_COLOR_BUFFER_BIT, GL_FRAGMENT_SHADER,
                    GL_LINEAR, GL_LINK_STATUS, GL_RGBA, GL_STREAM_DRAW,
                    GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_TEXTURE_MIN_FILTER,
                    GL_TRIANGLES, GL_UNSIGNED_BYTE, GL_VERTEX_SHADER, GL_COMPILE_STATUS)

GL_FRAMEBUFFER = 0x8D40
GL_FRAMEBUFFER_BINDING = 0x8CA6
GL_COLOR_ATTACHMENT0 = 0x8CE0
GL_FRAMEBUFFER_COMPLETE = 0x8CD5
GL_TEXTURE_WRAP_S = 0x2802
GL_TEXTURE_WRAP_T = 0x2803
GL_CLAMP_TO_EDGE = 0x812F
GL_BGRA = 0x80E1
GL_VIEWPORT = 0x0BA2
GL_COLOR_CLEAR_VALUE = 0x0C22
GL_CURRENT_PROGRAM = 0x8B8D
GL_VERTEX_ARRAY_BINDING = 0x85B5
GL_ARRAY_BUFFER_BINDING = 0x8894
GL_ACTIVE_TEXTURE = 0x84E0
GL_TEXTURE_BINDING_2D = 0x8069


def glass_rect(bar, area, pad):
    position = bar.translate_coordinates(area, 0, 0)
    if position is None:
        return None
    width, height = bar.get_allocated_width(), bar.get_allocated_height()
    if width < 2 or height < 2:
        return None
    return position[-2], position[-1] - pad, width, height + pad


def scene_quad(rect, scene_size):
    """Map a top-left-origin glass rectangle into the rendered GL texture."""
    x, y, width, height = rect
    scene_width, scene_height = scene_size
    u0, u1 = x / scene_width, (x + width) / scene_width
    v0, v1 = 1 - y / scene_height, 1 - (y + height) / scene_height
    return (ctypes.c_float * 24)(
        -1, 1, u0, v0, 1, 1, u1, v0, 1, -1, u1, v1,
        -1, 1, u0, v0, 1, -1, u1, v1, -1, -1, u0, v1)


def scene_covers_bar(rect, pad, scene_size):
    """Ignore blur padding when deciding whether the wall frame covers the bar."""
    x, y, width, height = rect
    scene_width, scene_height = scene_size
    return (x >= 0 and y + pad >= 0 and x + width <= scene_width and
            y + height <= scene_height)


class GPUBlur:
    """Render a small scene and convolve it on the GPU, then read back a small strip."""
    def __init__(self, gl):
        self.gl = gl
        self.buffers = {}
        self.program = self._program()
        self.scene_program = None
        self.vertical_program = None
        self.quad = (ctypes.c_float * 24)(
            -1, 1, 0, 1, 1, 1, 1, 1, 1, -1, 1, 0,
            -1, 1, 0, 1, 1, -1, 1, 0, -1, -1, 0, 0)

    def _program(self, direct_scene=False, vertical=False):
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
        vertex = compile_shader(GL_VERTEX_SHADER, b'''#version 150
in vec2 position; in vec2 texcoord; out vec2 uv;
void main() { uv=texcoord; gl_Position=vec4(position,0.0,1.0); }
''')
        fragment_source = b'''#version 150
uniform sampler2D image; in vec2 uv; out vec4 color;
void main() {
    vec2 step = 1.0 / vec2(textureSize(image, 0));
    vec4 value = vec4(0.0);
    float total = 0.0;
    for (int y = -2; y <= 2; ++y) {
        for (int x = -2; x <= 2; ++x) {
            float weight = exp(-float(x*x + y*y) / 2.0);
            value += texture(image, uv + vec2(x,y)*step) * weight;
            total += weight;
        }
    }
    color = value / total;
}
'''
        if direct_scene:
            # Blur densely at the source resolution before downsampling. Two
            # one-dimensional passes preserve small covers without 2D aliasing.
            step = (b'vec2(0.0, 1.0 / float(textureSize(image, 0).y))' if vertical
                    else b'vec2(fwidth(uv).x, 0.0)')
            fragment_source = b'''#version 150
uniform sampler2D image; in vec2 uv; out vec4 color;
vec4 sample_pixel(vec2 p) {
    if (any(lessThan(p, vec2(0.0))) || any(greaterThan(p, vec2(1.0))))
        return vec4(0.0);
    return texture(image, p);
}
void main() {
    vec2 step = STEP_VALUE;
    vec4 value = sample_pixel(uv) * 0.08271847;
    value += (sample_pixel(uv + step * 1.48500450) + sample_pixel(uv - step * 1.48500450)) * 0.15743930;
    value += (sample_pixel(uv + step * 3.46505705) + sample_pixel(uv - step * 3.46505705)) * 0.12915820;
    value += (sample_pixel(uv + step * 5.44522076) + sample_pixel(uv - step * 5.44522076)) * 0.09043469;
    value += (sample_pixel(uv + step * 7.42555748) + sample_pixel(uv - step * 7.42555748)) * 0.05404398;
    value += (sample_pixel(uv + step * 9.40612690) + sample_pixel(uv - step * 9.40612690)) * 0.02756460;
    color = value;
}
'''.replace(b'STEP_VALUE', step)
        fragment = compile_shader(GL_FRAGMENT_SHADER, fragment_source)
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
        return program

    def _release_pair(self, pair):
        gl = self.gl
        for name in ('source_fbo', 'horizontal_fbo', 'blur_fbo'):
            if pair[name].value:
                gl.glDeleteFramebuffers(1, ctypes.byref(pair[name]))
        for name in ('source_texture', 'horizontal_texture', 'blur_texture'):
            if pair[name].value:
                gl.glDeleteTextures(1, ctypes.byref(pair[name]))

    def _ensure(self, key, width, height, supersample=1):
        pair = self.buffers.get(key)
        if pair and pair['size'] == (width, height, supersample):
            return pair
        if pair:
            self._release_pair(pair)
        pair = {'size': (width, height, supersample), 'source_fbo': ctypes.c_uint(),
                'horizontal_fbo': ctypes.c_uint(), 'horizontal_texture': ctypes.c_uint(),
                'blur_fbo': ctypes.c_uint(), 'source_texture': ctypes.c_uint(),
                'blur_texture': ctypes.c_uint()}
        self.buffers[key] = pair
        gl = self.gl
        prefixes = ('source', 'horizontal', 'blur') if supersample > 1 else ('source', 'blur')
        for prefix in prefixes:
            texture, framebuffer = pair[prefix + '_texture'], pair[prefix + '_fbo']
            gl.glGenTextures(1, ctypes.byref(texture))
            gl.glBindTexture(GL_TEXTURE_2D, texture)
            gl.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
            gl.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
            gl.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
            gl.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
            factor = supersample if prefix != 'blur' else 1
            gl.glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, width * factor, height * factor, 0,
                            GL_RGBA, GL_UNSIGNED_BYTE, None)
            gl.glGenFramebuffers(1, ctypes.byref(framebuffer))
            gl.glBindFramebuffer(GL_FRAMEBUFFER, framebuffer)
            gl.glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
                                      GL_TEXTURE_2D, texture, 0)
            if gl.glCheckFramebufferStatus(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE:
                raise RuntimeError('GPU glass framebuffer is unavailable')
        return pair

    def render(self, key, width, height, vao, buffer, draw_scene, *,
               source_texture=None, source_rect=None, source_size=None, supersample=1):
        gl = self.gl
        def integer(name):
            value = ctypes.c_int()
            gl.glGetIntegerv(name, ctypes.byref(value))
            return value.value
        framebuffer = integer(GL_FRAMEBUFFER_BINDING)
        program = integer(GL_CURRENT_PROGRAM)
        vertex_array = integer(GL_VERTEX_ARRAY_BINDING)
        array_buffer = integer(GL_ARRAY_BUFFER_BINDING)
        active_texture = integer(GL_ACTIVE_TEXTURE)
        texture = integer(GL_TEXTURE_BINDING_2D)
        viewport = (ctypes.c_int * 4)()
        clear_color = (ctypes.c_float * 4)()
        gl.glGetIntegerv(GL_VIEWPORT, viewport)
        gl.glGetFloatv(GL_COLOR_CLEAR_VALUE, clear_color)
        try:
            supersample = max(2 if source_texture is not None else 1, int(supersample))
            pair = self._ensure(key, width, height, supersample)
            if source_texture is None:
                gl.glBindFramebuffer(GL_FRAMEBUFFER, pair['source_fbo'])
                gl.glViewport(0, 0, width * supersample, height * supersample)
                gl.glClearColor(0, 0, 0, 0)
                gl.glClear(GL_COLOR_BUFFER_BIT)
                draw_scene()
                texture_to_blur, quad = pair['source_texture'], self.quad
            else:
                if not source_rect or not source_size or min(source_size) <= 0:
                    raise ValueError('A valid source rectangle and size are required')
                texture_to_blur = source_texture
                quad = scene_quad(source_rect, source_size)
            if supersample > 1:
                if self.scene_program is None:
                    self.scene_program = self._program(direct_scene=True)
                if self.vertical_program is None:
                    self.vertical_program = self._program(direct_scene=True, vertical=True)
                gl.glBindFramebuffer(GL_FRAMEBUFFER, pair['horizontal_fbo'])
                gl.glViewport(0, 0, width * supersample, height * supersample)
                gl.glClearColor(0, 0, 0, 0)
                gl.glClear(GL_COLOR_BUFFER_BIT)
                gl.glUseProgram(self.scene_program)
                gl.glBindVertexArray(vao)
                gl.glBindBuffer(GL_ARRAY_BUFFER, buffer)
                gl.glBufferData(GL_ARRAY_BUFFER, ctypes.sizeof(quad), quad, GL_STREAM_DRAW)
                gl.glBindTexture(GL_TEXTURE_2D, texture_to_blur)
                gl.glDrawArrays(GL_TRIANGLES, 0, 6)
                texture_to_blur, program, quad = pair['horizontal_texture'], self.vertical_program, self.quad
            else:
                program = self.program
            gl.glBindFramebuffer(GL_FRAMEBUFFER, pair['blur_fbo'])
            gl.glViewport(0, 0, width, height)
            gl.glClearColor(0, 0, 0, 0)
            gl.glClear(GL_COLOR_BUFFER_BIT)
            gl.glUseProgram(program)
            gl.glBindVertexArray(vao)
            gl.glBindBuffer(GL_ARRAY_BUFFER, buffer)
            gl.glBufferData(GL_ARRAY_BUFFER, ctypes.sizeof(quad), quad, GL_STREAM_DRAW)
            gl.glBindTexture(GL_TEXTURE_2D, texture_to_blur)
            gl.glDrawArrays(GL_TRIANGLES, 0, 6)
            raw_surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
            raw = (ctypes.c_ubyte * (raw_surface.get_stride() * height)).from_buffer(
                raw_surface.get_data())
            gl.glReadPixels(0, 0, width, height, GL_BGRA, GL_UNSIGNED_BYTE, raw)
            error = gl.glGetError()
            if error:
                raise RuntimeError(f'GPU glass rendering failed ({error})')
            raw_surface.mark_dirty()
            surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
            context = cairo.Context(surface)
            context.translate(0, height)
            context.scale(1, -1)
            context.set_source_surface(raw_surface, 0, 0)
            context.paint()
            return surface
        finally:
            gl.glBindFramebuffer(GL_FRAMEBUFFER, framebuffer)
            gl.glViewport(*viewport)
            gl.glClearColor(*clear_color)
            gl.glUseProgram(program)
            gl.glBindVertexArray(vertex_array)
            gl.glBindBuffer(GL_ARRAY_BUFFER, array_buffer)
            gl.glActiveTexture(active_texture)
            gl.glBindTexture(GL_TEXTURE_2D, texture)

    def close(self):
        for pair in self.buffers.values():
            self._release_pair(pair)
        self.buffers.clear()
        if self.program:
            self.gl.glDeleteProgram(self.program)
            self.program = 0
        if self.scene_program:
            self.gl.glDeleteProgram(self.scene_program)
            self.scene_program = None
        if self.vertical_program:
            self.gl.glDeleteProgram(self.vertical_program)
            self.vertical_program = None
