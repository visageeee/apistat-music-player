# GPU album wall experiment

This standalone Linux prototype draws up to 256 cached covers in a single OpenGL texture atlas. It is an experiment, not the Apistat album wall: it does not show album names or support playback, flipping, selection, drag-and-drop, settings or Plex library sorting. Covers are chosen from the local artwork cache, which may contain artwork from multiple servers.

Run it after opening some albums in Apistat:

```bash
/usr/bin/python3 experiments/gpu_wall_probe.py
```

Scroll to move through the covers; hold Ctrl and scroll to change cover size. Resize the window normally. The probe requires GTK 3, PyGObject, GdkPixbuf, a working display and an OpenGL 3.2 core-capable driver (`libGL.so.1`). It is not packaged for Windows, macOS or Flatpak.

The following opens a window briefly, renders cached artwork, requests repeated resizes and checks OpenGL errors and framebuffer pixels:

```bash
/usr/bin/python3 experiments/gpu_wall_probe.py --self-test
```

This test checks basic rendering, not frame presentation latency or performance against the existing wall.
