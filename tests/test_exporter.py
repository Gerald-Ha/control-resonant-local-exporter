import struct
from argparse import Namespace
from contextlib import redirect_stdout
from io import StringIO
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from resonant_exporter import (ArchiveCatalog, ExportError, DELUXE_TITLES, KNOWN_MIXTAPE,
                              export, export_artbook, list_artbook_entries, get_banks, parse_wwise_media_id, safe_filename,
                              load_external_backend, locate_pc_dir, missing_tool_messages,
                              wizard, check_output_not_game)


def build_bank(media_id=346045306, plugin=0x40001, stream_type=2):
    sound = (struct.pack('<I', 903336770) + struct.pack('<I', plugin) +
             bytes([stream_type]) + struct.pack('<I', media_id) + bytes(12))
    obj = b'\x02' + struct.pack('<I', len(sound)) + sound
    hirc = struct.pack('<I', 1) + obj
    return b'BKHD' + struct.pack('<I', 4) + b'\x00'*4 + b'HIRC' + struct.pack('<I', len(hirc)) + hirc


class ParserTests(unittest.TestCase):
    def test_valid_media_id(self):
        self.assertEqual(parse_wwise_media_id(build_bank()), 346045306)

    def test_truncated_bank(self):
        with self.assertRaises(ExportError):
            parse_wwise_media_id(build_bank()[:-1])

    def test_unsupported_codec(self):
        with self.assertRaises(ExportError):
            parse_wwise_media_id(build_bank(plugin=42))

    def test_no_sound(self):
        with self.assertRaises(ExportError):
            parse_wwise_media_id(b'BKHD\x00\x00\x00\x00')

    def test_safe_filename(self):
        self.assertEqual(safe_filename('../X:Song|A'), '_X_Song_A')

    def test_resolve_track(self):
        with tempfile.TemporaryDirectory() as root:
            game = Path(root)
            # This is a fake backend, so tests require no third-party parser or copyrighted data.
            banks = {'full_name': 'banks/play_menu_another_world.bnk'}
            media = {'full_name': 'media/346045306.wem'}
            backend = Mock()
            backend.decode_toc.side_effect = [
                {'files': [banks, media]}, {'files': []}
            ]
            def extraction(model, entry, blobs, target):
                Path(target).write_bytes(build_bank() if entry is banks else b'FAKE WEM')
            backend.extract_file.side_effect = extraction
            cat = ArchiveCatalog(game, backend)
            track = cat.resolve_track('Zoe', 1, 'Another World',
                                      banks['full_name'], 'base-generic.rmdtoc', game)
            self.assertEqual(track.media_id, 346045306)
            self.assertEqual(track.audio_archive, 'base-generic.rmdtoc')


    def test_full_19_track_dry_run(self):
        with tempfile.TemporaryDirectory() as root:
            game = Path(root) / 'pc'
            game.mkdir()
            base_paths = [path for path, _ in KNOWN_MIXTAPE]
            stream_paths = [f'banks/play_music_deluxe_{i:02d}_test.bnk'
                            for i in range(1, len(DELUXE_TITLES) + 1)]
            base = [{'full_name': name} for name in base_paths]
            stream = [{'full_name': name} for name in stream_paths]
            ids = list(range(1234, 1234 + len(base_paths) + len(stream_paths)))
            for i, media_id in enumerate(ids):
                arr = base if i < len(base_paths) else stream
                arr.append({'full_name': f'media/{media_id}.wem'})
            bank_to_id = {path: ids[i] for i, path in enumerate(base_paths + stream_paths)}
            backend = Mock()
            backend.decode_toc.side_effect = [{'files': base}, {'files': stream}]
            def extraction(model, entry, blobs, target):
                source_path = entry['full_name']
                if source_path.endswith('.bnk'):
                    Path(target).write_bytes(build_bank(bank_to_id[source_path]))
                else:
                    Path(target).write_bytes(b'fake wem')
            backend.extract_file.side_effect = extraction
            catalog = ArchiveCatalog(game, backend)
            args = Namespace(group='all', bank=[], output=str(Path(root) / 'export'),
                             dry_run=True, format='flac', vgmstream=None,
                             overwrite=False)
            with redirect_stdout(StringIO()) as out:
                export(catalog, args)
            self.assertIn('Validated 19 media IDs', out.getvalue())
            self.assertIn('Dry-run complete', out.getvalue())
            self.assertFalse((Path(root) / 'export').exists())



    def test_six_song_mixtape_is_officially_ordered(self):
        names = [title for _, title in KNOWN_MIXTAPE]
        self.assertEqual(names, [
            'Say What',
            'No Chains Can Last Forever',
            'Another World',
            "A World I'm Ready to Live and Die For",
            'Fight for Control (We Go To War)',
            'Manalan Mailla',
        ])
        with tempfile.TemporaryDirectory() as root:
            backend = Mock()
            backend.decode_toc.side_effect = [
                {'files': [{'full_name': bank} for bank, _ in KNOWN_MIXTAPE]},
                {'files': []},
            ]
            catalog = ArchiveCatalog(Path(root), backend)
            specs = get_banks(catalog, 'mixtape', [])
            self.assertEqual(len(specs), 6)
            self.assertEqual([spec[1] for spec in specs], [1, 2, 3, 4, 5, 6])
            self.assertEqual([spec[2] for spec in specs], names)
            self.assertTrue(all(spec[-1] == 'base-generic.rmdtoc' for spec in specs))

    def test_legacy_exports_warn_without_mutation(self):
        from resonant_exporter import warn_legacy_mixtape_outputs
        with tempfile.TemporaryDirectory() as root:
            output = Path(root)
            mixtape = output / "Zoe's Mixtape"
            mixtape.mkdir()
            old = mixtape / '01 - Another World.flac'
            old.write_bytes(b'keep original contents')
            with redirect_stdout(StringIO()) as captured:
                warn_legacy_mixtape_outputs(output)
            self.assertIn('WARNING:', captured.getvalue())
            self.assertEqual(old.read_bytes(), b'keep original contents')

    def test_dynamic_backend_import_registers_dataclass_module(self):
        # Regression: Python 3.14 dataclasses requires sys.modules registration.
        with tempfile.TemporaryDirectory() as root:
            external = Path(root) / 'crack.py'
            external.write_text(
                'from dataclasses import dataclass\n'
                '@dataclass\nclass Record:\n    name: str\n'
                'def decode_toc(path): pass\n'
                'def resolve_blobs(model): pass\n'
                'def extract_file(model, entry, blobs, target): pass\n'
            )
            module = load_external_backend(external)
            self.assertEqual(module.Record('ok').name, 'ok')
            self.assertIs(sys.modules[module.__name__], module)

    def test_missing_tools_has_download_instructions(self):
        with tempfile.TemporaryDirectory() as root:
            messages = missing_tool_messages(Path(root))
            self.assertEqual(len(messages), 2)
            self.assertEqual(len(missing_tool_messages(Path(root), need_audio=False)), 1)
            self.assertIn('github.com/UmFzbXVz/', messages[0])
            self.assertIn('https://vgmstream.org/', messages[1])

    def test_present_tools_are_recognized(self):
        with tempfile.TemporaryDirectory() as root:
            tools = Path(root)
            (tools / 'crack.py').write_text('# stub')
            decoder = tools / 'vgmstream-cli'
            decoder.write_text('#!/bin/sh\n')
            decoder.chmod(0o755)
            self.assertEqual(missing_tool_messages(tools), [])

    def test_wizard_without_tools_stops_before_prompting(self):
        with tempfile.TemporaryDirectory() as root:
            with patch('resonant_exporter.TOOLS_DIR', Path(root)), \
                 patch('builtins.input', side_effect=['3']):
                with redirect_stdout(StringIO()) as captured:
                    result = wizard()
            self.assertEqual(result, 2)
            self.assertIn('python3 resonant_exporter.py', captured.getvalue())

    def test_wizard_prompts_for_directories_and_runs_export(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            tools = root / 'tools'
            tools.mkdir()
            (tools / 'crack.py').write_text('# provided external stub')
            decoder = tools / 'vgmstream-cli'
            decoder.write_text('#!/bin/sh\n')
            decoder.chmod(0o755)
            game = root / 'game' / 'data_pack2' / 'pc'
            game.mkdir(parents=True)
            for toc in ('base-generic.rmdtoc', 'stream0-generic.rmdtoc'):
                (game / toc).write_bytes(b'placeholder')
            output = root / 'music'
            answers = ['1', str(game), str(output), 'wav', 'y']
            with patch('resonant_exporter.TOOLS_DIR', tools), \
                 patch('builtins.input', side_effect=answers), \
                 patch('resonant_exporter.importlib.util.find_spec', return_value=object()), \
                 patch('resonant_exporter.load_external_backend', return_value=Mock()), \
                 patch('resonant_exporter.ArchiveCatalog', return_value=Mock()) as catalog_cls, \
                 patch('resonant_exporter.export_music') as run_export:
                with redirect_stdout(StringIO()):
                    rc = wizard()
            self.assertEqual(rc, 0)
            catalog_cls.assert_called_once()
            args = run_export.call_args.args[1]
            self.assertEqual(args.output, str(output))
            self.assertEqual(args.format, 'wav')
            self.assertEqual(args.group, 'all')

    def test_artbook_filter_only_large_images(self):
        samples = {name: {'full_name': name} for name in (
            'artbook/piece_small.tex', 'artbook/piece_medium.tex',
            'artbook/piece_large.tex', 'artbook/another_large.tex',
            'unrelated/also_large.tex',
        )}
        self.assertEqual([i['full_name'] for i in list_artbook_entries(samples)],
                         ['artbook/another_large.tex', 'artbook/piece_large.tex'])

    def test_artbook_dry_run_is_read_only(self):
        with tempfile.TemporaryDirectory() as root:
            backend = Mock()
            backend.decode_toc.side_effect = [
                {'files': [{'full_name': 'artbook/sample_large.tex'}]}, {'files': []},
            ]
            catalog = ArchiveCatalog(Path(root) / 'pc', backend)
            args = Namespace(output=str(Path(root) / 'output'),
                             dry_run=True, overwrite=False, keep_dds=False)
            with redirect_stdout(StringIO()) as output:
                export_artbook(catalog, args)
            self.assertIn('Found 1 large Deluxe artbook images', output.getvalue())
            self.assertFalse((Path(root) / 'output').exists())
            backend.extract_file.assert_not_called()

    def test_cannot_export_inside_game_installation(self):
        game = Path('/tmp/controlresonant/data_pack2/pc')
        with self.assertRaises(ExportError):
            check_output_not_game(Path('/tmp/controlresonant/output'), game)
        with self.assertRaises(ExportError):
            check_output_not_game(Path('/tmp/controlresonant/data_pack2/pc/out'), game)


if __name__ == '__main__':
    unittest.main()
