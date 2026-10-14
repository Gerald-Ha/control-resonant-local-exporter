"""End-to-end CLI smoke test with synthetic banks and external tools.

No game or third-party source code is embedded in this test.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path


PARSER_STUB = '''
from dataclasses import dataclass
from pathlib import Path
import struct

@dataclass
class FakeModel:
    files: list

BASE = [
    'banks/play_menu_say_what.bnk',
    'banks/play_menu_no_chains_can_last_forever.bnk',
    'banks/play_menu_another_world.bnk',
    'banks/play_menu_world_im_ready_to_live_and_die_for.bnk',
    'banks/play_menu_fight_for_control.bnk',
    'banks/play_menu_manalan_mailla.bnk',
]
STREAM = [f'banks/play_music_deluxe_{i:02d}_test.bnk' for i in range(1, 14)]
ARTBOOK = [f'artbook/synthetic_{i:02d}_large.tex' for i in range(1, 4)]
NAMES = BASE + STREAM
MAPPINGS = {name: 9000 + n for n, name in enumerate(NAMES)}

def decode_toc(path):
    names = BASE + ARTBOOK if Path(path).name == 'base-generic.rmdtoc' else STREAM
    return {'files': [{'full_name': name} for name in names] +
                     [{'full_name': f'media/{MAPPINGS[name]}.wem'} for name in names if name in MAPPINGS]}

def resolve_blobs(model):
    return None

def extract_file(model, entry, blobs, target):
    name = entry['full_name']
    if name.endswith('.wem'):
        Path(target).write_bytes(b'PLACEHOLDER WEM, no game content')
        return
    if name.endswith('.tex'):
        Path(target).write_bytes(b'DDS ' + bytes(124))
        return
    media_id = MAPPINGS[name]
    sound = (struct.pack('<I', 123456) + struct.pack('<I', 0x40001) +
             bytes([2]) + struct.pack('<I', media_id) + bytes(12))
    obj = bytes([2]) + struct.pack('<I', len(sound)) + sound
    hirc = struct.pack('<I', 1) + obj
    data = (b'BKHD' + struct.pack('<I', 4) + b'\\0'*4 +
            b'HIRC' + struct.pack('<I', len(hirc)) + hirc)
    Path(target).write_bytes(data)
'''

FAKE_FFMPEG_STUB = r'''#!/usr/bin/env python3
import sys, struct, zlib
from pathlib import Path

def chunk(name, data):
    return struct.pack('>I', len(data)) + name + data + struct.pack('>I', zlib.crc32(name + data) & 0xffffffff)
png = (b"\x89PNG\r\n\x1a\n" +
       chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0)) +
       chunk(b'IDAT', zlib.compress(b"\x00\x00\x00\x00")) +
       chunk(b'IEND', b''))
Path(sys.argv[-1]).write_bytes(png)
'''


DECODER_STUB = '''#!/usr/bin/env python3
import sys
import wave
from pathlib import Path
p = Path(sys.argv[sys.argv.index('-o') + 1])
with wave.open(str(p), 'wb') as wav:
    wav.setnchannels(2)
    wav.setsampwidth(2)
    wav.setframerate(48000)
    wav.writeframes(b'\\x00' * 1920)
'''


class WizardIntegrationTests(unittest.TestCase):
    def test_wizard_full_wav_export_uses_external_backend(self):
        source = Path(__file__).resolve().parents[1] / 'resonant_exporter.py'
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app = root / 'exporter'
            app.mkdir()
            shutil.copyfile(source, app / 'resonant_exporter.py')
            tools = app / 'tools'
            tools.mkdir()
            (tools / 'crack.py').write_text(PARSER_STUB)
            decoder = tools / 'vgmstream-cli'
            decoder.write_text(DECODER_STUB)
            decoder.chmod(0o755)
            game = root / 'Game Install' / 'data_pack2' / 'pc'
            game.mkdir(parents=True)
            for toc in ('base-generic.rmdtoc', 'stream0-generic.rmdtoc'):
                (game / toc).write_bytes(b'synthetic index')
            output = root / 'Music Export'
            answers = f'1\n{game}\n{output}\nwav\ny\n'
            done = subprocess.run([sys.executable, 'resonant_exporter.py'],
                                  cwd=app, input=answers, text=True,
                                  capture_output=True, timeout=30)
            self.assertEqual(done.returncode, 0, done.stdout + '\n' + done.stderr)
            tracks = list(output.rglob('*.wav'))
            self.assertEqual(len(tracks), 19)
            mixtape = output / "Zoe's Mixtape"
            self.assertEqual([p.name for p in sorted(mixtape.glob('*.wav'))], [
                '01 - Say What.wav',
                '02 - No Chains Can Last Forever.wav',
                '03 - Another World.wav',
                "04 - A World I'm Ready to Live and Die For.wav",
                '05 - Fight for Control (We Go To War).wav',
                '06 - Manalan Mailla.wav',
            ])
            with wave.open(str(tracks[0]), 'rb') as audio:
                self.assertEqual(audio.getframerate(), 48000)
            for toc in ('base-generic.rmdtoc', 'stream0-generic.rmdtoc'):
                self.assertEqual((game / toc).read_bytes(), b'synthetic index')

    def test_both_exports_audio_and_artbook_via_wizard(self):
        source = Path(__file__).resolve().parents[1] / 'resonant_exporter.py'
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app = root / 'app'
            app.mkdir()
            shutil.copyfile(source, app / 'resonant_exporter.py')
            tools = app / 'tools'
            tools.mkdir()
            (tools / 'crack.py').write_text(PARSER_STUB)
            decoder = tools / 'vgmstream-cli'
            decoder.write_text(DECODER_STUB)
            decoder.chmod(0o755)
            helper_bin = root / 'bin'
            helper_bin.mkdir()
            ffmpeg = helper_bin / 'ffmpeg'
            ffmpeg.write_text(FAKE_FFMPEG_STUB)
            ffmpeg.chmod(0o755)
            game = root / 'Control Resonant' / 'data_pack2' / 'pc'
            game.mkdir(parents=True)
            for toc in ('base-generic.rmdtoc', 'stream0-generic.rmdtoc'):
                (game / toc).write_bytes(b'synthetic index')
            output = root / 'Output'
            import os
            env = dict(os.environ, PATH=str(helper_bin) + os.pathsep + os.environ['PATH'])
            # Both mode, local installation root, WAV for music.
            answers = f'3\n{game.parent.parent}\n{output}\nwav\ny\n'
            done = subprocess.run([sys.executable, 'resonant_exporter.py'], cwd=app,
                                  input=answers, text=True, capture_output=True,
                                  timeout=60, env=env)
            self.assertEqual(done.returncode, 0, done.stdout + '\n' + done.stderr)
            self.assertEqual(len(list(output.rglob('*.wav'))), 19)
            artbook = output / 'Deluxe Artbook'
            self.assertEqual(len(list((artbook / 'png').glob('*.png'))), 3)
            self.assertEqual(len((artbook / 'manifest.txt').read_text().splitlines()), 3)
            gallery = (artbook / 'index.html').read_text()
            self.assertIn('lang="en"', gallery)
            self.assertIn('synthetic_01_large.png', gallery)
            self.assertFalse((artbook / '_dds').exists())
            for toc in ('base-generic.rmdtoc', 'stream0-generic.rmdtoc'):
                self.assertEqual((game / toc).read_bytes(), b'synthetic index')

    def test_artbook_only_does_not_require_audio_decoder(self):
        source = Path(__file__).resolve().parents[1] / 'resonant_exporter.py'
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app = root / 'app'
            app.mkdir()
            shutil.copyfile(source, app / 'resonant_exporter.py')
            tools = app / 'tools'
            tools.mkdir()
            (tools / 'crack.py').write_text(PARSER_STUB)
            helper_bin = root / 'bin'
            helper_bin.mkdir()
            ffmpeg = helper_bin / 'ffmpeg'
            ffmpeg.write_text(FAKE_FFMPEG_STUB)
            ffmpeg.chmod(0o755)
            game = root / 'Game' / 'data_pack2' / 'pc'
            game.mkdir(parents=True)
            for toc in ('base-generic.rmdtoc', 'stream0-generic.rmdtoc'):
                (game / toc).write_bytes(b'synthetic index')
            output = root / 'Images'
            import os
            env = dict(os.environ, PATH=str(helper_bin) + os.pathsep + os.environ['PATH'])
            answers = f'2\n{game}\n{output}\ny\n'
            done = subprocess.run([sys.executable, 'resonant_exporter.py'], cwd=app,
                                  input=answers, text=True, capture_output=True,
                                  timeout=60, env=env)
            self.assertEqual(done.returncode, 0, done.stdout + '\n' + done.stderr)
            self.assertEqual(len(list(output.rglob('*.png'))), 3)
            self.assertEqual(len(list(output.rglob('*.wav'))), 0)



if __name__ == '__main__':
    unittest.main()
