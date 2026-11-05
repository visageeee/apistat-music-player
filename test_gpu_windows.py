"""Windows GPU context and loader behavior, including non-Windows mocks."""
import ctypes
import unittest
from unittest.mock import Mock, patch

import gpu_gl
import gpu_offscreen
from gpu_wgl import PixelFormatDescriptor, WindowsOffscreenGPU


class Function:
    def __init__(self, result=None, side_effect=None):
        self.mock = Mock(return_value=result, side_effect=side_effect)
    def __call__(self, *args):
        return self.mock(*args)


class FakeLibrary:
    def __init__(self, functions):
        for name, function in functions.items():
            setattr(self, name, function)


class WindowsGPUTests(unittest.TestCase):
    def test_pixel_format_descriptor_matches_win32_layout(self):
        self.assertEqual(ctypes.sizeof(PixelFormatDescriptor), 40)
        self.assertEqual(PixelFormatDescriptor.dwFlags.offset, 4)
        self.assertEqual(PixelFormatDescriptor.dwLayerMask.offset, 28)

    def test_gl_functions_resolve_lazily_with_a_current_context(self):
        callback_type = ctypes.CFUNCTYPE(ctypes.c_uint, ctypes.c_uint)
        callback = callback_type(lambda value: value + 3)
        address = ctypes.cast(callback, ctypes.c_void_p).value
        get_proc = Function(result=address)
        library = FakeLibrary({'wglGetProcAddress': get_proc})
        loader = gpu_gl.WindowsGL(library)
        loader.register('glCreateShader', ctypes.c_uint, [ctypes.c_uint])
        get_proc.mock.assert_not_called()
        with patch.object(ctypes, 'WINFUNCTYPE', ctypes.CFUNCTYPE, create=True):
            self.assertEqual(loader.glCreateShader(4), 7)
            self.assertEqual(loader.glCreateShader(5), 8)
        get_proc.mock.assert_called_once_with(b'glCreateShader')

    def test_invalid_wgl_function_pointer_fails_cleanly(self):
        loader = gpu_gl.WindowsGL(FakeLibrary({'wglGetProcAddress': Function(result=1)}))
        loader.register('glCreateShader', ctypes.c_uint, [ctypes.c_uint])
        with self.assertRaisesRegex(RuntimeError, 'unavailable'):
            loader.glCreateShader

    def test_offscreen_factory_chooses_windows_context(self):
        gl = object()
        with patch.object(gpu_offscreen.sys, 'platform', 'win32'), \
                patch('gpu_wgl.WindowsOffscreenGPU', return_value='context') as create:
            self.assertEqual(gpu_offscreen.create_offscreen_gpu(gl), 'context')
        create.assert_called_once_with(gl)

    def test_context_creation_replaces_bootstrap_and_releases_resources(self):
        create_type = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                                      ctypes.POINTER(ctypes.c_int))
        create = create_type(lambda _dc, _shared, _attributes: 303)
        address = ctypes.cast(create, ctypes.c_void_p).value
        user = FakeLibrary({'CreateWindowExW': Function(101), 'GetDC': Function(202),
                            'ReleaseDC': Function(1), 'DestroyWindow': Function(1)})
        gdi = FakeLibrary({'ChoosePixelFormat': Function(1), 'SetPixelFormat': Function(1)})
        wgl = FakeLibrary({'wglCreateContext': Function(302), 'wglMakeCurrent': Function(1),
                           'wglDeleteContext': Function(1), 'wglGetCurrentContext': Function(None),
                           'wglGetCurrentDC': Function(None)})
        gl = Mock(library=wgl, get_proc=Mock(return_value=address))
        with patch.object(ctypes, 'WinDLL', side_effect=[user, gdi], create=True), \
                patch.object(ctypes, 'WINFUNCTYPE', ctypes.CFUNCTYPE, create=True), \
                patch('gpu_wgl.Gdk.GLContext.get_current', return_value=None):
            gpu = WindowsOffscreenGPU(gl)
        self.assertEqual(gpu.context, 303)
        wgl.wglDeleteContext.mock.assert_called_once_with(302)
        gpu.close()
        self.assertEqual(wgl.wglDeleteContext.mock.call_args_list[-1].args, (303,))
        user.ReleaseDC.mock.assert_called_once_with(101, 202)
        user.DestroyWindow.mock.assert_called_once_with(101)

    def test_missing_modern_context_cleans_up_bootstrap_resources(self):
        user = FakeLibrary({'CreateWindowExW': Function(101), 'GetDC': Function(202),
                            'ReleaseDC': Function(1), 'DestroyWindow': Function(1)})
        gdi = FakeLibrary({'ChoosePixelFormat': Function(1), 'SetPixelFormat': Function(1)})
        wgl = FakeLibrary({'wglCreateContext': Function(302), 'wglMakeCurrent': Function(1),
                           'wglDeleteContext': Function(1), 'wglGetCurrentContext': Function(None),
                           'wglGetCurrentDC': Function(None)})
        gl = Mock(library=wgl, get_proc=Mock(return_value=0))
        with patch.object(ctypes, 'WinDLL', side_effect=[user, gdi], create=True), \
                patch('gpu_wgl.Gdk.GLContext.get_current', return_value=None):
            with self.assertRaisesRegex(RuntimeError, '3.2'):
                WindowsOffscreenGPU(gl)
        wgl.wglDeleteContext.mock.assert_called_once_with(302)
        user.ReleaseDC.mock.assert_called_once_with(101, 202)
        user.DestroyWindow.mock.assert_called_once_with(101)

    def test_windows_context_preserves_existing_wgl_context(self):
        gpu = WindowsOffscreenGPU.__new__(WindowsOffscreenGPU)
        gpu.dc, gpu.context = 20, 30
        gpu.wgl = FakeLibrary({'wglGetCurrentContext': Function(90),
                               'wglGetCurrentDC': Function(80),
                               'wglMakeCurrent': Function(1)})
        with patch('gpu_wgl.Gdk.GLContext.get_current', return_value=None):
            with gpu.current():
                gpu.wgl.wglMakeCurrent.mock.assert_called_once_with(20, 30)
        self.assertEqual(gpu.wgl.wglMakeCurrent.mock.call_args_list[-1].args, (80, 90))

    def test_failed_context_activation_restores_previous_context(self):
        gpu = WindowsOffscreenGPU.__new__(WindowsOffscreenGPU)
        gpu.dc, gpu.context = 20, 30
        gpu.wgl = FakeLibrary({'wglGetCurrentContext': Function(90),
                               'wglGetCurrentDC': Function(80),
                               'wglMakeCurrent': Function(side_effect=[0, 1])})
        with patch('gpu_wgl.Gdk.GLContext.get_current', return_value=None):
            with self.assertRaises(RuntimeError):
                with gpu.current():
                    self.fail('failed context should not be used')
        self.assertEqual(gpu.wgl.wglMakeCurrent.mock.call_args_list[-1].args, (80, 90))


if __name__ == '__main__':
    unittest.main()
