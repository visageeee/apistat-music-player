"""Render artwork gradients in a private OpenGL framebuffer for GTK."""
import ctypes
from array import array

import cairo

from gpu_gl import (load_gl, GL_VERTEX_SHADER, GL_FRAGMENT_SHADER, GL_COMPILE_STATUS,
                    GL_LINK_STATUS, GL_TRIANGLES, GL_UNSIGNED_BYTE)
from gpu_offscreen import create_offscreen_gpu, GL_BGRA


def _compile(gl, kind, source):
    shader = gl.glCreateShader(kind)
    data = ctypes.c_char_p(source)
    gl.glShaderSource(shader, 1, ctypes.byref(data), None)
    gl.glCompileShader(shader)
    status = ctypes.c_int()
    gl.glGetShaderiv(shader, GL_COMPILE_STATUS, ctypes.byref(status))
    if not status.value:
        gl.glDeleteShader(shader)
        raise RuntimeError('Gradient shader compilation failed')
    return shader


def render_gpu_gradient(width, height, colors):
    """Return a Cairo surface rendered offscreen; never create a GTK GL surface."""
    if width < 1 or height < 1:
        raise ValueError('Invalid gradient size')
    gl = load_gl()
    target = create_offscreen_gpu(gl)
    program = 0
    vao = ctypes.c_uint()
    try:
        with target.current():
            vertex = _compile(gl, GL_VERTEX_SHADER, b'''#version 150
void main() {
    vec2 p = vec2((gl_VertexID == 1) ? 3.0 : -1.0,
                  (gl_VertexID == 2) ? 3.0 : -1.0);
    gl_Position = vec4(p, 0.0, 1.0);
}''')
            try:
                first, second = [tuple(int(color[i:i+2], 16) / 255.0 for i in (1, 3, 5))
                                 for color in colors]
                dx, dy = max(1, width - 1), max(1, height - 1)
                fragment = ('''#version 150
out vec4 color;
void main() {
    vec2 p = gl_FragCoord.xy - vec2(0.5);
    vec2 extent = vec2(%(dx)d.0, %(dy)d.0);
    float amount = clamp(dot(p, extent) / dot(extent, extent), 0.0, 1.0);
    vec3 first = vec3(%(r0).9f, %(g0).9f, %(b0).9f);
    vec3 second = vec3(%(r1).9f, %(g1).9f, %(b1).9f);
    // A one-code-value ordered threshold distributes 8-bit rounding without
    // the visible grain of a multi-level noise overlay.
    ivec2 cell = ivec2(gl_FragCoord.xy) %% 4;
    int bayer[16] = int[16](0, 8, 2, 10, 12, 4, 14, 6,
                              3, 11, 1, 9, 15, 7, 13, 5);
    float threshold = (float(bayer[cell.y * 4 + cell.x]) + 0.5) / 16.0;
    vec3 value = floor(clamp(mix(first, second, amount), 0.0, 1.0) * 255.0 + threshold) / 255.0;
    color = vec4(value, 1.0);
}''' % dict(dx=dx, dy=dy, r0=first[0], g0=first[1], b0=first[2],
            r1=second[0], g1=second[1], b1=second[2])).encode('ascii')
                pixel_shader = _compile(gl, GL_FRAGMENT_SHADER, fragment)
                try:
                    program = gl.glCreateProgram()
                    gl.glAttachShader(program, vertex)
                    gl.glAttachShader(program, pixel_shader)
                    gl.glLinkProgram(program)
                    status = ctypes.c_int()
                    gl.glGetProgramiv(program, GL_LINK_STATUS, ctypes.byref(status))
                    if not status.value:
                        raise RuntimeError('Gradient shader linking failed')
                finally:
                    gl.glDeleteShader(pixel_shader)
            finally:
                gl.glDeleteShader(vertex)
            gl.glGenVertexArrays(1, ctypes.byref(vao))
            gl.glBindVertexArray(vao)
            target.target(width, height)
            gl.glViewport(0, 0, width, height)
            gl.glDisable(0x0BD0)  # GL_DITHER; the shader controls rounding.
            gl.glUseProgram(program)
            gl.glDrawArrays(GL_TRIANGLES, 0, 3)
            pixels = array('I', [0]) * (width * height)
            buffer = (ctypes.c_ubyte * (width * height * 4)).from_buffer(pixels)
            gl.glReadPixels(0, 0, width, height, GL_BGRA, GL_UNSIGNED_BYTE, buffer)
            if gl.glGetError():
                raise RuntimeError('Gradient GPU readback failed')
            surface = cairo.ImageSurface.create_for_data(
                pixels, cairo.FORMAT_ARGB32, width, height, width * 4)
            return surface, pixels
    finally:
        try:
            with target.current():
                if vao.value:
                    gl.glDeleteVertexArrays(1, ctypes.byref(vao))
                if program:
                    gl.glDeleteProgram(program)
                target.release_target()
        finally:
            target.close()
