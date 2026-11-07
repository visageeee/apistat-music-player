"""Run in the optional Demucs Python environment, never in the GTK process."""
from pathlib import Path
import struct
import sys
import wave

try:
    import numpy as np
except ModuleNotFoundError:
    raise SystemExit(21)  # Missing NumPy in the external environment.

# A line maps to one stem and one frequency band. Bands distinguish, for
# example, kick/snare/cymbals within the isolated drum stem.
BANDS = (
    ('bass', 30, 130), ('bass', 130, 350), ('bass', 350, 1500),
    ('drums', 35, 150), ('drums', 150, 1400), ('drums', 1400, 10000),
    ('vocals', 100, 500), ('vocals', 500, 1600), ('vocals', 1600, 8000),
    ('other', 80, 350), ('other', 350, 1000), ('other', 1000, 3000), ('other', 3000, 10000),
)
HOP_MS = 50


def stem_bands(path, bands):
    with wave.open(str(path), 'rb') as source:
        if source.getsampwidth() != 2 or source.getnchannels() not in (1, 2):
            raise ValueError('Expected 16-bit mono or stereo stems')
        channels, rate = source.getnchannels(), source.getframerate()
        hop = max(1, round(rate * HOP_MS / 1000))
        frequencies = np.fft.rfftfreq(hop, 1 / rate)
        masks = [(frequencies >= low) & (frequencies < min(high, rate / 2)) for low, high in bands]
        window = np.hanning(hop)
        result = []
        while True:
            data = source.readframes(hop)
            if not data:
                break
            samples = np.frombuffer(data, dtype='<i2').astype(np.float32)
            samples = samples.reshape(-1, channels).mean(axis=1) / 32768.
            if len(samples) < hop:
                samples = np.pad(samples, (0, hop - len(samples)))
            spectrum = np.abs(np.fft.rfft(samples * window)) / max(1, hop / 2)
            # Sum spectral energy instead of mean, so quiet bands stay quiet.
            result.append([min(1., (float(np.sqrt(np.sum(spectrum[mask] ** 2))) * 3.0) ** .7)
                           for mask in masks])
        return result


def build_analysis(directory, output, duration):
    by_stem = {}
    for stem in ('bass', 'drums', 'vocals', 'other'):
        ranges = [(low, high) for name, low, high in BANDS if name == stem]
        by_stem[stem] = stem_bands(directory / (stem + '.wav'), ranges)
    count = max(map(len, by_stem.values()), default=0)
    if not count or count > 20 * 60 * 60:
        raise ValueError('Invalid analysis length')
    result = bytearray(struct.pack('!4sIII', b'ASI1', duration, HOP_MS, count))
    for frame in range(count):
        for stem in ('bass', 'drums', 'vocals', 'other'):
            rows = by_stem[stem]
            values = rows[frame] if frame < len(rows) else [0.] * sum(x[0] == stem for x in BANDS)
            result.extend(round(max(0., min(1., value)) * 255) for value in values)
    output.write_bytes(result)


def main():
    if len(sys.argv) != 4:
        raise SystemExit(2)
    source, output, duration = Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3])
    try:
        from demucs.separate import main as separate
    except ModuleNotFoundError:
        raise SystemExit(22)  # Demucs or one of its dependencies is missing.
    directory = output.parent / 'stems'
    # CPU and one thread avoid contention with playback and the UI.
    separate(['-n', 'htdemucs', '-d', 'cpu', '--shifts', '0', '-o', str(directory), str(source)])
    build_analysis(directory / 'htdemucs' / source.stem, output, duration)


if __name__ == '__main__':
    main()
