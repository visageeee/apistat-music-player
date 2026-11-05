"""OpenGL core-profile primitives for the album wall."""
import ctypes
import sys

GL_TEXTURE_2D = 0x0DE1
GL_TEXTURE0 = 0x84C0
GL_BLEND = 0x0BE2
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


class WindowsGL:
    """Resolve modern functions in the current WGL context, not at import time."""
    def __init__(self, library=None):
        self.library = library or ctypes.WinDLL('opengl32.dll')
        self.get_proc = self.library.wglGetProcAddress
        self.get_proc.argtypes = [ctypes.c_char_p]
        self.get_proc.restype = ctypes.c_void_p
        self.signatures = {}

    def register(self, name, result, args):
        self.signatures[name] = result, args

    def __getattr__(self, name):
        if name not in self.signatures:
            raise AttributeError(name)
        result, args = self.signatures[name]
        try:
            function = getattr(self.library, name)
            function.restype, function.argtypes = result, args
        except AttributeError:
            address = self.get_proc(name.encode('ascii'))
            if address in (None, 0, 1, 2, 3, ctypes.c_void_p(-1).value):
                raise RuntimeError(f'OpenGL function {name} is unavailable')
            function = ctypes.WINFUNCTYPE(result, *args)(address)
        setattr(self, name, function)
        return function


def load_gl():
    gl = WindowsGL() if sys.platform == 'win32' else ctypes.CDLL('libGL.so.1')
    signatures = {
        'glGetString': (ctypes.c_char_p, [ctypes.c_uint]),
        'glGetError': (ctypes.c_uint, []),
        'glGetIntegerv': (None, [ctypes.c_uint, ctypes.POINTER(ctypes.c_int)]),
        'glGetFloatv': (None, [ctypes.c_uint, ctypes.POINTER(ctypes.c_float)]),
        'glClearColor': (None, [ctypes.c_float] * 4),
        'glClear': (None, [ctypes.c_uint]),
        'glEnable': (None, [ctypes.c_uint]),
        'glDisable': (None, [ctypes.c_uint]),
        'glViewport': (None, [ctypes.c_int] * 4),
        'glGenTextures': (None, [ctypes.c_int, ctypes.POINTER(ctypes.c_uint)]),
        'glBindTexture': (None, [ctypes.c_uint, ctypes.c_uint]),
        'glActiveTexture': (None, [ctypes.c_uint]),
        'glTexParameteri': (None, [ctypes.c_uint, ctypes.c_uint, ctypes.c_int]),
        'glTexImage2D': (None, [ctypes.c_uint, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, ctypes.c_uint, ctypes.c_uint,
                                ctypes.c_void_p]),
        'glTexSubImage2D': (None, [ctypes.c_uint, ctypes.c_int, ctypes.c_int, ctypes.c_int,
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
        'glGenFramebuffers': (None, [ctypes.c_int, ctypes.POINTER(ctypes.c_uint)]),
        'glBindFramebuffer': (None, [ctypes.c_uint, ctypes.c_uint]),
        'glFramebufferTexture2D': (None, [ctypes.c_uint, ctypes.c_uint, ctypes.c_uint,
                                          ctypes.c_uint, ctypes.c_int]),
        'glCheckFramebufferStatus': (ctypes.c_uint, [ctypes.c_uint]),
        'glDeleteFramebuffers': (None, [ctypes.c_int, ctypes.POINTER(ctypes.c_uint)]),
    }
    for name, (result, args) in signatures.items():
        if isinstance(gl, WindowsGL):
            gl.register(name, result, args)
        else:
            fn = getattr(gl, name)
            fn.restype, fn.argtypes = result, args
    return gl



class GLProgram:
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
void main() { vec4 sample_color = texture(image, uv);
              color = vec4(sample_color.rgb * sample_color.a, sample_color.a); }
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
