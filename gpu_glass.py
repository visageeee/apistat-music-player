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


class GPUBlur:
    """Render a small scene and convolve it on the GPU, then read back a small strip."""
    def __init__(self, gl):
        self.gl = gl
        self.buffers = {}
        self.program = self._program()
        self.quad = (ctypes.c_float * 24)(
            -1, 1, 0, 1, 1, 1, 1, 1, 1, -1, 1, 0,
            -1, 1, 0, 1, 1, -1, 1, 0, -1, -1, 0, 0)

    def _program(self):
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
        fragment = compile_shader(GL_FRAGMENT_SHADER, b'''#version 150
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
''')
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
        for name in ('source_fbo', 'blur_fbo'):
            if pair[name].value:
                gl.glDeleteFramebuffers(1, ctypes.byref(pair[name]))
        for name in ('source_texture', 'blur_texture'):
            if pair[name].value:
                gl.glDeleteTextures(1, ctypes.byref(pair[name]))

    def _ensure(self, key, width, height):
        pair = self.buffers.get(key)
        if pair and pair['size'] == (width, height):
            return pair
        if pair:
            self._release_pair(pair)
        pair = {'size': (width, height), 'source_fbo': ctypes.c_uint(),
                'blur_fbo': ctypes.c_uint(), 'source_texture': ctypes.c_uint(),
                'blur_texture': ctypes.c_uint()}
        self.buffers[key] = pair
        gl = self.gl
        for prefix in ('source', 'blur'):
            texture, framebuffer = pair[prefix + '_texture'], pair[prefix + '_fbo']
            gl.glGenTextures(1, ctypes.byref(texture))
            gl.glBindTexture(GL_TEXTURE_2D, texture)
            gl.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
            gl.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
            gl.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
            gl.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
            gl.glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, width, height, 0,
                            GL_RGBA, GL_UNSIGNED_BYTE, None)
            gl.glGenFramebuffers(1, ctypes.byref(framebuffer))
            gl.glBindFramebuffer(GL_FRAMEBUFFER, framebuffer)
            gl.glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
                                      GL_TEXTURE_2D, texture, 0)
            if gl.glCheckFramebufferStatus(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE:
                raise RuntimeError('GPU glass framebuffer is unavailable')
        return pair

    def render(self, key, width, height, vao, buffer, draw_scene):
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
            pair = self._ensure(key, width, height)
            gl.glBindFramebuffer(GL_FRAMEBUFFER, pair['source_fbo'])
            gl.glViewport(0, 0, width, height)
            gl.glClearColor(0, 0, 0, 0)
            gl.glClear(GL_COLOR_BUFFER_BIT)
            draw_scene()
            gl.glBindFramebuffer(GL_FRAMEBUFFER, pair['blur_fbo'])
            gl.glViewport(0, 0, width, height)
            gl.glClear(GL_COLOR_BUFFER_BIT)
            gl.glUseProgram(self.program)
            gl.glBindVertexArray(vao)
            gl.glBindBuffer(GL_ARRAY_BUFFER, buffer)
            gl.glBufferData(GL_ARRAY_BUFFER, ctypes.sizeof(self.quad), self.quad, GL_STREAM_DRAW)
            gl.glBindTexture(GL_TEXTURE_2D, pair['source_texture'])
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
