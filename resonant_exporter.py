#!/usr/bin/env python3
"""Export music and Deluxe Artbook images from a local Control Resonant installation."""
from __future__ import annotations

import argparse
import html
import importlib.util
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent
TOOLS_DIR = PROJECT_ROOT / "tools"
APP_VERSION = "0.4.1"
PARSER_URL = "https://github.com/UmFzbXVz/Control-Resonant-asset-conversion-kit"
DECODER_URL = "https://vgmstream.org/"

DELUXE_TITLES = (
    "Tabula Rasa", "Into the Sunshine", "Obsessive Compulsive Order",
    "Activate - Execute", "Thrown Out", "Back to Zero", "The Cell",
    "Entity in Gap", "Sibling Theme (Broken Conduit)", "Final Conduit Pt. 2",
    "Final Fight", "Final Conclusion",
    "The One I Once Knew (feat. Amelia Jones)",
)
KNOWN_MIXTAPE = (
    ("banks/play_menu_say_what.bnk", "Say What"),
    ("banks/play_menu_no_chains_can_last_forever.bnk", "No Chains Can Last Forever"),
    ("banks/play_menu_another_world.bnk", "Another World"),
    ("banks/play_menu_world_im_ready_to_live_and_die_for.bnk",
     "A World I'm Ready to Live and Die For"),
    ("banks/play_menu_fight_for_control.bnk", "Fight for Control (We Go To War)"),
    ("banks/play_menu_manalan_mailla.bnk", "Manalan Mailla"),
)
TOCS = ("base-generic.rmdtoc", "stream0-generic.rmdtoc")


class ExportError(RuntimeError):
    """Export or validation error."""


@dataclass(frozen=True)
class Track:
    collection: str
    index: int
    title: str
    bank_archive: str
    bank_path: str
    audio_archive: str
    media_id: int
    entry: Any


def safe_filename(name: str) -> str:
    cleaned = re.sub(r'[\\/<>:"|?*\x00-\x1f]', "_", name).strip(" .")
    return (cleaned[:140].rstrip(" .") or "untitled")


def parse_wwise_media_id(bank: bytes) -> int:
    """Read one media ID from a supported Wwise bank."""
    offset = 0
    has_header = False
    ids: list[int] = []
    while offset < len(bank):
        if offset + 8 > len(bank):
            raise ExportError("Truncated Wwise section header")
        tag = bank[offset:offset + 4]
        size = struct.unpack_from("<I", bank, offset + 4)[0]
        end = offset + 8 + size
        if end > len(bank):
            raise ExportError("Wwise section exceeds file size")
        if tag == b"BKHD":
            has_header = True
        elif tag == b"HIRC":
            if size < 4:
                raise ExportError("Invalid HIRC section")
            count = struct.unpack_from("<I", bank, offset + 8)[0]
            if count > 50_000:
                raise ExportError("Unreasonable HIRC object count")
            cursor = offset + 12
            for _ in range(count):
                if cursor + 5 > end:
                    raise ExportError("Truncated HIRC object")
                obj_type = bank[cursor]
                length = struct.unpack_from("<I", bank, cursor + 1)[0]
                obj_start = cursor + 5
                obj_end = obj_start + length
                if length < 4 or obj_end > end:
                    raise ExportError("Invalid HIRC object length")
                if obj_type == 2:
                    if length < 13:
                        raise ExportError("Unsupported short Wwise Sound object")
                    plugin = struct.unpack_from("<I", bank, obj_start + 4)[0]
                    stream_type = bank[obj_start + 8]
                    if plugin != 0x00040001 or stream_type not in (0, 1, 2):
                        raise ExportError(
                            f"Unsupported Sound encoding: plugin=0x{plugin:08x}, "
                            f"stream={stream_type}"
                        )
                    media_id = struct.unpack_from("<I", bank, obj_start + 9)[0]
                    if media_id == 0:
                        raise ExportError("Empty Wwise media ID")
                    ids.append(media_id)
                cursor = obj_end
            if cursor != end:
                raise ExportError("HIRC object sizes do not match section size")
        offset = end
    if not has_header or len(ids) != 1:
        raise ExportError(f"Expected BKHD and one Sound object; found {len(ids)}")
    return ids[0]


def load_external_backend(path: Path):
    if not path.is_file():
        raise ExportError(
            f"Archive parser not found: {path}\n"
            f"Download crack.py separately from {PARSER_URL} "
            "and place it in the tools/ directory."
        )
    spec = importlib.util.spec_from_file_location("user_supplied_crack", path)
    if spec is None or spec.loader is None:
        raise ExportError("External archive parser could not be loaded")
    module = importlib.util.module_from_spec(spec)
    # Register the module before executing it so @dataclass can resolve its types.
    previous = sys.modules.get(spec.name)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        if previous is None:
            sys.modules.pop(spec.name, None)
        else:
            sys.modules[spec.name] = previous
        raise
    for symbol in ("decode_toc", "resolve_blobs", "extract_file"):
        if not callable(getattr(module, symbol, None)):
            raise ExportError(f"External parser is missing {symbol}()")
    return module


def locate_pc_dir(path: Path) -> Path:
    root = path.expanduser().resolve()
    for item in (root, root / "data_pack2" / "pc"):
        if all((item / toc).is_file() for toc in TOCS):
            return item
    raise ExportError(
        "Could not find base-generic.rmdtoc and stream0-generic.rmdtoc. "
        "Enter the game installation folder or data_pack2/pc."
    )


class ArchiveCatalog:
    def __init__(self, root: Path, backend: Any):
        self.root = root
        self.backend = backend
        self.models: dict[str, Any] = {}
        self.index: dict[str, dict[str, Any]] = {}
        for toc in TOCS:
            model = backend.decode_toc(root / toc)
            self.models[toc] = model
            self.index[toc] = {entry["full_name"]: entry for entry in model["files"]}
        self.blobs: dict[str, Any] = {}

    def lookup(self, resource: str, prefer: str | None = None):
        archives = ([prefer] if prefer else []) + [t for t in TOCS if t != prefer]
        for archive in archives:
            entry = self.index[archive].get(resource)
            if entry is not None:
                return archive, entry
        raise ExportError(f"Missing archive resource: {resource}")

    def extract(self, archive: str, entry: Any, output: Path):
        output.parent.mkdir(parents=True, exist_ok=True)
        if archive not in self.blobs:
            self.blobs[archive] = self.backend.resolve_blobs(self.models[archive])
        self.backend.extract_file(self.models[archive], entry, self.blobs[archive], output)
        if not output.is_file() or output.stat().st_size == 0:
            raise ExportError(f"Empty extracted resource: {output}")

    def resolve_track(self, collection: str, index: int, title: str,
                      bank_path: str, bank_archive: str, tempdir: Path) -> Track:
        archive, entry = self.lookup(bank_path, bank_archive)
        temp = tempdir / f"bank-{collection}-{index:02d}.bnk"
        self.extract(archive, entry, temp)
        media_id = parse_wwise_media_id(temp.read_bytes())
        audio_archive, audio_entry = self.lookup(f"media/{media_id}.wem", archive)
        return Track(collection, index, title, archive, bank_path,
                     audio_archive, media_id, audio_entry)


def get_banks(catalog: ArchiveCatalog, group: str, extras: list[str]):
    results = []
    if group in ("deluxe", "all"):
        for idx, title in enumerate(DELUXE_TITLES, 1):
            prefix = f"banks/play_music_deluxe_{idx:02d}_"
            matches = sorted(
                k for k in catalog.index["stream0-generic.rmdtoc"]
                if k.startswith(prefix) and k.endswith(".bnk")
            )
            if len(matches) != 1:
                raise ExportError(f"Expected one bank matching {prefix}; found {len(matches)}")
            results.append(("Deluxe Soundtrack", idx, title, matches[0],
                            "stream0-generic.rmdtoc"))
    if group in ("mixtape", "all"):
        for idx, (path, title) in enumerate(KNOWN_MIXTAPE, 1):
            results.append(("Zoe's Mixtape", idx, title, path, "base-generic.rmdtoc"))
    for idx, path in enumerate(extras, 1):
        path = path.strip()
        if not path.startswith("banks/") or not path.endswith(".bnk") or ".." in Path(path).parts:
            raise ExportError(f"Invalid banks/*.bnk path: {path}")
        title = path.removeprefix("banks/play_menu_").removeprefix("banks/").removesuffix(".bnk")
        results.append(("Other Selected Music", idx, title.replace("_", " ").title(),
                        path, "base-generic.rmdtoc"))
    return results


def scan(catalog: ArchiveCatalog):
    print("Music-related soundbanks found in local archives:\n")
    for toc in TOCS:
        banks = sorted(p for p in catalog.index[toc]
                       if p.startswith("banks/") and p.endswith(".bnk")
                       and p.startswith(("banks/play_music_deluxe_",
                                         "banks/play_menu_", "banks/play_mus_diegetic_")))
        print(f"[{toc}] {len(banks)} soundbanks")
        for path in banks:
            print(" ", path)
    print("\nDeluxe artbook image entries:")
    for toc in TOCS:
        selected = list_artbook_entries(catalog.index[toc])
        print(f"[{toc}]: {len(selected)} *_large.tex files")


def list_artbook_entries(resources: dict[str, Any]) -> list[Any]:
    return [resources[path] for path in sorted(resources)
            if path.startswith("artbook/") and path.endswith("_large.tex")]


def get_decoder(path: str | None) -> Path:
    decoder = (Path(path).expanduser().resolve() if path
               else Path(shutil.which("vgmstream-cli") or ""))
    if not decoder.is_file() or not decoder.stat().st_mode & 0o111:
        raise ExportError(f"vgmstream-cli missing or not executable: {decoder}")
    return decoder


def check_output_not_game(output: Path, game: Path):
    installation = (game.parent.parent if game.name == "pc" and game.parent.name == "data_pack2"
                    else game)
    if output == installation or installation in output.parents:
        raise ExportError("Output directory must be outside the game installation")


def require_ffmpeg() -> str:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise ExportError("ffmpeg is required for Artbook PNG or FLAC export; install ffmpeg first")
    return ffmpeg


def warn_legacy_mixtape_outputs(output: Path):
    mixtape = output / "Zoe's Mixtape"
    old_titles = (
        "01 - Another World",
        "02 - A World I'm Ready to Live and Die For",
    )
    legacy = [p for stem in old_titles for p in mixtape.glob(stem + ".*")
              if p.is_file() and p.suffix.lower() in (".wav", ".flac")]
    if legacy:
        print("WARNING: Output contains Zoe's Mixtape exports with v0.3 track numbers.")
        print("  v0.4 uses the official six-track order (Another World is #03).")
        print("  Existing files will NOT be deleted or renamed automatically.")
        print("  Use a fresh output folder or remove the outdated copies yourself:")
        for p in sorted(legacy):
            print(f"    {p}")


def export_music(catalog: ArchiveCatalog, args):
    out = Path(args.output).expanduser().resolve()
    check_output_not_game(out, catalog.root)
    banks = get_banks(catalog, args.group, args.bank)
    if not banks:
        raise ExportError("No music banks selected")
    with tempfile.TemporaryDirectory(prefix="resonant-music-") as scratch:
        temp = Path(scratch)
        tracks = [catalog.resolve_track(*spec, temp) for spec in banks]
        print(f"Validated {len(tracks)} media IDs (local game archives).")
        for track in tracks:
            print(f"  {track.collection}: {track.title}: media/{track.media_id}.wem")
        if args.dry_run:
            print("Dry-run complete; no audio exported.")
            return
        decoder = get_decoder(args.vgmstream)
        ffmpeg = require_ffmpeg() if args.format == "flac" else None
        out.mkdir(parents=True, exist_ok=True)
        if args.group in ("mixtape", "all"):
            warn_legacy_mixtape_outputs(out)
        for track in tracks:
            dest_dir = out / safe_filename(track.collection)
            dest_dir.mkdir(parents=True, exist_ok=True)
            stem = f"{track.index:02d} - {safe_filename(track.title)}"
            dest = dest_dir / f"{stem}.{args.format}"
            if dest.exists() and not args.overwrite:
                print(f"SKIP (already exists): {dest}")
                continue
            with tempfile.TemporaryDirectory(prefix="track-", dir=out) as tmp:
                tmpdir = Path(tmp)
                wem = tmpdir / f"{track.media_id}.wem"
                wav = tmpdir / "decoded.wav"
                catalog.extract(track.audio_archive, track.entry, wem)
                subprocess.run([str(decoder), "-o", str(wav), str(wem)], check=True)
                if not wav.is_file() or not wav.stat().st_size:
                    raise ExportError(f"Audio decoder returned no WAV for {track.title}")
                result = tmpdir / f"result.{args.format}"
                if args.format == "flac":
                    subprocess.run([
                        ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                        "-i", str(wav), "-map", "0:a:0", "-c:a", "flac",
                        "-metadata", f"title={track.title}",
                        "-metadata", f"track={track.index}",
                        "-metadata", f"album={track.collection}", str(result),
                    ], check=True)
                else:
                    wav.replace(result)
                if not result.is_file() or not result.stat().st_size:
                    raise ExportError(f"Conversion failed: {track.title}")
                result.replace(dest)
            print(f"OK: {dest}")
    print(f"Music export complete: {out}")


def build_artbook_gallery(images: list[Path], artbook_dir: Path):
    manifest = artbook_dir / "manifest.txt"
    manifest.write_text("\n".join(f"artbook/{img.stem}.tex" for img in images) + "\n",
                        encoding="utf-8")
    page = [
        '<!doctype html>', '<html lang="en">', '<head>', '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        '<title>Control Resonant - Deluxe Artbook</title>',
        '<style>',
        'body{font-family:system-ui,sans-serif;background:#111;color:#eee;margin:24px}',
        'p{color:#bbb}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:16px}',
        '.card{background:#1c1c1c;padding:10px;border-radius:10px}',
        'img{width:100%;height:auto;display:block;border-radius:6px;background:#000}',
        '.name{margin-top:8px;font-size:14px;overflow-wrap:anywhere}',
        '</style>', '</head>', '<body>',
        '<h1>Control Resonant - Deluxe Artbook</h1>',
        '<p>Offline gallery created from your locally installed game files.</p>',
        f'<p>{len(images)} images</p>', '<div class="grid">',
    ]
    for image in images:
        rel = html.escape(f"png/{image.name}", quote=True)
        name = html.escape(image.stem)
        page.append(f'<div class="card"><a href="{rel}"><img src="{rel}" '
                    f'alt="{name}" loading="lazy"></a><div class="name">{name}</div></div>')
    page.extend(['</div>', '</body>', '</html>'])
    (artbook_dir / "index.html").write_text("\n".join(page) + "\n", encoding="utf-8")


def export_artbook(catalog: ArchiveCatalog, args):
    out = Path(args.output).expanduser().resolve()
    check_output_not_game(out, catalog.root)
    archive = "base-generic.rmdtoc"
    entries = list_artbook_entries(catalog.index[archive])
    if not entries:
        raise ExportError("No artbook/*_large.tex assets found in base-generic.rmdtoc")
    print(f"Found {len(entries)} large Deluxe artbook images.")
    if args.dry_run:
        for entry in entries:
            print(f"  {entry['full_name']}")
        print("Dry-run complete; no images exported.")
        return
    ffmpeg = require_ffmpeg()
    artbook = out / "Deluxe Artbook"
    png_dir = artbook / "png"
    dds_dir = artbook / "_dds"
    png_dir.mkdir(parents=True, exist_ok=True)
    if args.keep_dds:
        dds_dir.mkdir(parents=True, exist_ok=True)
    for idx, entry in enumerate(entries, 1):
        original = Path(entry["full_name"]).stem
        stem = safe_filename(original)
        if stem != original:
            raise ExportError(f"Unexpected artbook filename: {original}")
        png = png_dir / f"{stem}.png"
        dds_copy = dds_dir / f"{stem}.dds"
        if png.is_file() and png.stat().st_size > 0 and not args.overwrite and (
            not args.keep_dds or dds_copy.is_file()
        ):
            print(f"[{idx}/{len(entries)}] SKIP (already exists): {png.name}")
            continue
        with tempfile.TemporaryDirectory(prefix="art-", dir=artbook) as tmp:
            temp = Path(tmp)
            dds = temp / f"{stem}.dds"
            result = temp / "converted.png"
            catalog.extract(archive, entry, dds)
            with dds.open("rb") as src:
                magic = src.read(4)
            if magic != b"DDS ":
                raise ExportError(f"Unexpected image format (expected DDS): {entry['full_name']}")
            if args.keep_dds and (args.overwrite or not dds_copy.is_file()):
                shutil.copyfile(dds, temp / "raw.dds")
            if args.overwrite or not png.is_file() or not png.stat().st_size:
                subprocess.run([
                    ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                    "-i", str(dds), "-frames:v", "1", str(result),
                ], check=True)
                if not result.is_file() or result.stat().st_size < 8:
                    raise ExportError(f"PNG conversion failed: {entry['full_name']}")
                with result.open("rb") as src:
                    png_magic = src.read(8)
                if png_magic != b"\x89PNG\r\n\x1a\n":
                    raise ExportError(f"PNG conversion failed: {entry['full_name']}")
                result.replace(png)
            if args.keep_dds and (args.overwrite or not dds_copy.is_file()):
                (temp / "raw.dds").replace(dds_copy)
        print(f"[{idx}/{len(entries)}] OK: {png.name}", flush=True)
    images = sorted(png_dir.glob("*.png"))
    build_artbook_gallery(images, artbook)
    print(f"Artbook export complete: {len(images)} PNG files")
    print(f"Gallery: {artbook / 'index.html'}")


def missing_tool_messages(tools_dir: Path = TOOLS_DIR, *, need_audio: bool = True) -> list[str]:
    messages = []
    parser = tools_dir / "crack.py"
    decoder = tools_dir / "vgmstream-cli"
    if not parser.is_file():
        messages.append(
            f"MISSING: {parser}\n"
            f"  1. Open {PARSER_URL}\n"
            "  2. Download the repository (Code > Download ZIP, or git clone).\n"
            "  3. Copy crack.py to tools/crack.py."
        )
    if need_audio and (not decoder.is_file() or not decoder.stat().st_mode & 0o111):
        messages.append(
            f"MISSING OR NOT EXECUTABLE: {decoder}\n"
            f"  1. Open {DECODER_URL}\n"
            "  2. Choose the Linux Command-line (static build) download.\n"
            "  3. Copy vgmstream-cli to tools/vgmstream-cli.\n"
            "  4. Run: chmod +x tools/vgmstream-cli"
        )
    return messages


def normalize_user_path(value: str) -> Path:
    raw = value.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in ('"', "'"):
        raw = raw[1:-1]
    return Path(raw).expanduser().resolve()


def ask_path(prompt: str, *, default: Path | None = None, validator=None) -> Path:
    while True:
        suffix = f" [{default}]" if default else ""
        raw = input(f"{prompt}{suffix}: ").strip()
        if not raw:
            if default is None:
                print("Please enter a path (Ctrl+C to cancel).")
                continue
            choice = default
        else:
            choice = normalize_user_path(raw)
        try:
            return validator(choice) if validator else choice
        except (ExportError, OSError) as exc:
            print(f"Invalid path: {exc}")


def select_content() -> str:
    print("[1/4] Select content")
    print("  1. Music (13 Deluxe Soundtrack + 6 Zoe's Mixtape tracks)")
    print("  2. Deluxe Artbook (large images and offline HTML gallery)")
    print("  3. Both (default)")
    while True:
        value = input("Selection [1/2/3] [3]: ").strip() or "3"
        if value in ("1", "2", "3"):
            return {"1": "music", "2": "artbook", "3": "both"}[value]
        print("Please choose 1, 2, or 3.")


def wizard() -> int:
    print(f"\nCONTROL RESONANT - Local Exporter v{APP_VERSION} (Linux)\n")
    mode = select_content()
    need_music = mode in ("music", "both")
    need_artbook = mode in ("artbook", "both")
    print("\n[2/4] Check external tools")
    messages = missing_tool_messages(TOOLS_DIR, need_audio=need_music)
    if messages:
        print("The following separately obtained files are required:")
        for message in messages:
            print(f"\n{message}")
        print("\nNo files were downloaded. Copy the tools and run again:")
        print("  python3 resonant_exporter.py")
        return 2
    print(f"OK: {TOOLS_DIR / 'crack.py'}")
    if need_music:
        print(f"OK: {TOOLS_DIR / 'vgmstream-cli'}")
    if importlib.util.find_spec("lz4") is None:
        print("\nMISSING: Python package 'lz4'. On Fedora: sudo dnf install python3-lz4")
        print("Alternatively, inside a virtual environment: python -m pip install lz4")
        return 2
    if need_artbook and not shutil.which("ffmpeg"):
        print("\nMISSING: ffmpeg is required for DDS to PNG conversion.")
        return 2
    print("\n[3/4] Choose paths")
    print("Enter the game installation folder or directly the data_pack2/pc folder.")
    game = ask_path("Game directory", validator=locate_pc_dir)

    def validate_output(path: Path) -> Path:
        check_output_not_game(path, game)
        if path.exists() and not path.is_dir():
            raise ExportError("Output destination is a file, not a directory")
        return path

    default_out = (Path.home() / "Music/Control-Resonant/Exported" if mode == "music"
                   else Path.home() / "Pictures/Control-Resonant/Exported" if mode == "artbook"
                   else Path.home() / "Control-Resonant-Exports")
    output = ask_path("Output directory", default=default_out, validator=validate_output)
    fmt = "flac"
    if need_music:
        default_format = "flac" if shutil.which("ffmpeg") else "wav"
        while True:
            value = input(f"Audio format [flac/wav] [{default_format}]: ").strip().lower()
            fmt = value or default_format
            if fmt not in ("flac", "wav"):
                print("Please enter flac or wav.")
            elif fmt == "flac" and not shutil.which("ffmpeg"):
                print("FLAC requires ffmpeg. Install it or choose WAV.")
            else:
                break
    print("\n[4/4] Summary")
    print(f"Game archives: {game}")
    print(f"Output:        {output}")
    print(f"Content:       {mode}")
    if need_music:
        print(f"Audio format:  {fmt}")
    if need_artbook:
        print("Artbook:       *_large.tex -> PNG + offline HTML gallery")
    print("Game archives will not be modified. Existing outputs will be skipped.")
    if input("Start export? [y/N]: ").strip().lower() not in ("y", "yes"):
        print("Cancelled. No files exported.")
        return 0
    backend = load_external_backend(TOOLS_DIR / "crack.py")
    catalog = ArchiveCatalog(game, backend)
    if need_music:
        export_music(catalog, argparse.Namespace(
            output=str(output), group="all", bank=[], dry_run=False,
            format=fmt, vgmstream=str(TOOLS_DIR / "vgmstream-cli"), overwrite=False,
        ))
    if need_artbook:
        export_artbook(catalog, argparse.Namespace(
            output=str(output), dry_run=False, overwrite=False, keep_dds=False,
        ))
    return 0


def cli(argv=None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    try:
        if not argv or argv == ["wizard"]:
            return wizard()
        parser = argparse.ArgumentParser(description="Local Control Resonant music and artbook exporter")
        parser.add_argument("--game-root", help="Game installation or data_pack2/pc directory")
        parser.add_argument("--crack", help="Path to the separately obtained crack.py parser")
        sub = parser.add_subparsers(dest="command", required=True)
        sub.add_parser("wizard", help="Start the interactive workflow")
        sub.add_parser("scan", help="List candidate music banks and count artbook assets")
        music = sub.add_parser("export", aliases=["music"], help="Export locally installed music")
        music.add_argument("--group", choices=("deluxe", "mixtape", "all", "none"), default="all")
        music.add_argument("--bank", action="append", default=[], help="Extra bank path reported by scan")
        music.add_argument("--format", choices=("wav", "flac"), default="flac")
        music.add_argument("--vgmstream", help="Path to the separately obtained vgmstream-cli")
        music.add_argument("--output", default=str(Path.home() / "Music/Control-Resonant/Exported"))
        music.add_argument("--dry-run", action="store_true")
        music.add_argument("--overwrite", action="store_true")
        art = sub.add_parser("artbook", help="Export large Deluxe artbook images to PNG + HTML gallery")
        art.add_argument("--output", default=str(Path.home() / "Pictures/Control-Resonant/Exported"))
        art.add_argument("--dry-run", action="store_true")
        art.add_argument("--overwrite", action="store_true")
        art.add_argument("--keep-dds", action="store_true", help="Also preserve original extracted DDS files")
        args = parser.parse_args(argv)
        if args.command == "wizard":
            return wizard()
        if not args.game_root:
            parser.error("--game-root is required for scan/export/artbook; or run with no arguments")
        game = locate_pc_dir(Path(args.game_root))
        parser_path = (Path(args.crack).expanduser().resolve() if args.crack
                       else TOOLS_DIR / "crack.py" if (TOOLS_DIR / "crack.py").is_file()
                       else game / "crack.py")
        backend = load_external_backend(parser_path)
        catalog = ArchiveCatalog(game, backend)
        if args.command == "scan":
            scan(catalog)
        elif args.command == "artbook":
            export_artbook(catalog, args)
        else:
            if not args.dry_run and not args.vgmstream and (TOOLS_DIR / "vgmstream-cli").is_file():
                args.vgmstream = str(TOOLS_DIR / "vgmstream-cli")
            export_music(catalog, args)
    except (ExportError, ValueError, OSError, KeyError, ModuleNotFoundError,
            subprocess.CalledProcessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        return 130
    return 0


# Backward-compatible name.
export = export_music

if __name__ == "__main__":
    sys.exit(cli())
