# Control Resonant Local Exporter

An **unofficial, local-only Linux exporter** for music and Deluxe Artbook assets from a legitimately installed copy of *Control Resonant*. Tested on Fedora with **19 music tracks** and **201 Artbook PNGs** successfully exported, alongside automated tests using synthetic files.

It contains **no game assets, third-party programs, or decryption keys**. It reads your local game archives using a separately obtained parser. See [LEGAL.md](LEGAL.md) for legal and publication considerations.

## Why this project exists

**If you bought it, you should be able to enjoy it offline.** I believe buying a game and its digital extras should mean more than being allowed to view or play them only while the game is running. A soundtrack is worth listening to outside the game. An artbook is worth browsing whenever you want.

This tool is intended **only for personal use with your own legally purchased copy of Control Resonant and a valid license to access its content**. It does not give you permission to share, publish, or sell the extracted music or artwork.

## What it can export

- **Deluxe Soundtrack:** 13 identified tracks, as WAV or FLAC.
- **Zoe's Mixtape:** All **six** identified tracks in the official album order. Four previously missing soundbanks were validated in the local game archives by the user (see track list below).
- **Deluxe Artbook:** `artbook/*_large.tex` entries from `base-generic.rmdtoc`. These were verified as DDS images. On the tested game install, **201 images** were exported at full available `large` resolution.
- **Offline Artbook gallery:** `index.html` and `manifest.txt`, referencing local exported PNGs.
- Optional retention of the extracted DDS files via `--keep-dds` (command-line only). By default only PNGs are kept, so no extra multi-gigabyte DDS collection remains.

### Zoe's Mixtape track list

| # | Song | Local Wwise soundbank |
|---|---|---|
| 01 | Say What | `banks/play_menu_say_what.bnk` |
| 02 | No Chains Can Last Forever | `banks/play_menu_no_chains_can_last_forever.bnk` |
| 03 | Another World | `banks/play_menu_another_world.bnk` |
| 04 | A World I'm Ready to Live and Die For | `banks/play_menu_world_im_ready_to_live_and_die_for.bnk` |
| 05 | Fight for Control (We Go To War) | `banks/play_menu_fight_for_control.bnk` |
| 06 | Manalan Mailla | `banks/play_menu_manalan_mailla.bnk` |

The exporter resolves the Wwise media IDs from the installed soundbanks at runtime. It does not need a hard-coded list of audio IDs to extract the data.

The utility skips already existing exports unless `--overwrite` is used. **It never modifies the original game archives.** It does not export the Artbook's in-game captions, artist credits, categories, or presentation metadata; these are not yet mapped.

## Requirements

- Python 3.10+ and Python module `lz4`
- Locally installed game files (`base-generic.rmdtoc`, `stream0-generic.rmdtoc`, related `.rmdblob` files)
- Separately obtained **`crack.py`** archive parser, available from <https://github.com/UmFzbXVz/Control-Resonant-asset-conversion-kit>
- Separately obtained **`vgmstream-cli`** *if exporting music*, download from **<https://vgmstream.org/>** → **Linux / Command-line (static build)**
- System **FFmpeg** for Artbook PNG or FLAC export (music as WAV works without FFmpeg)

### Prepare the `tools/` folder

The project intentionally ships with an empty tools directory (only `.gitkeep` is tracked):

```text
control-resonant-local-exporter/
├── resonant_exporter.py
├── tools/
│   ├── .gitkeep
│   ├── crack.py          # add yourself from the separate upstream repository
│   └── vgmstream-cli     # add yourself from https://vgmstream.org/
├── tests/
├── README.md
├── LEGAL.md
├── CHANGELOG.md
└── LICENSE
```

1. Download or clone the archive parser repository. Copy **only `crack.py`** to `tools/crack.py`. Inspect third-party scripts before running them: the exporter executes this script when reading archives.
2. For music export, visit **https://vgmstream.org/**, choose the Linux **Command-line (static build)** download, and copy `vgmstream-cli` to `tools/`.
3. Make the executable runnable:

```bash
chmod +x tools/vgmstream-cli
```

4. Install any missing system dependencies. For Fedora, for example:

```bash
sudo dnf install python3-lz4 ffmpeg
```

Depending on your enabled repositories, `ffmpeg` packaging may vary. Check with `command -v ffmpeg`. If your system already has the commands and Python module, do not reinstall them.

**No network downloads are performed by the exporter.** Neither the parser nor the audio decoder is redistributed here; check their respective terms yourself.

## Interactive usage

```bash
python3 resonant_exporter.py
```

The wizard will:

1. Ask whether to export **Music**, **Deluxe Artbook**, or **Both** (default).
2. Check required tools. The decoder is not required for Artbook-only export; FFmpeg is required for Artbook PNG export.
3. Ask for the **game installation directory** (the main `Control Resonant` folder or `data_pack2/pc`) and an **output directory**. Paths can contain spaces or underscores.
4. If music is selected, ask for **WAV** or **FLAC**.
5. Show a summary and request confirmation before exporting.

Example output when **Both** is selected:

```text
<selected output directory>/
├── Deluxe Soundtrack/
│   ├── 01 - Tabula Rasa.flac
│   └── ...
├── Zoe's Mixtape/
│   ├── 01 - Say What.flac
│   ├── 02 - No Chains Can Last Forever.flac
│   ├── 03 - Another World.flac
│   ├── 04 - A World I'm Ready to Live and Die For.flac
│   ├── 05 - Fight for Control (We Go To War).flac
│   └── 06 - Manalan Mailla.flac
└── Deluxe Artbook/
    ├── index.html
    ├── manifest.txt
    └── png/
        ├── deluxe_dp_early_explo_01_large.png
        └── ...
```

Open `Deluxe Artbook/index.html` in your browser. Images remain local and are not uploaded anywhere.

### Upgrading from v0.3.0

v0.3.0 saved only two Mixtape tracks, numbered **01 - Another World** and **02 - A World I'm Ready to Live and Die For**. Their correct full-album positions are **03** and **04**. v0.4.0 does **not** delete, rename, or overwrite previously exported files automatically. If you export v0.4 into the old output directory, a warning identifies those legacy files, which will otherwise coexist alongside the new six-track set. For a clean result, export to a fresh folder or manually remove those two old, misnumbered copies after verifying the new versions.

## Advanced command-line examples

All examples assume `tools/crack.py` is present. For music, also install `tools/vgmstream-cli`.

```bash
GAME="$HOME/Games/control-resonant/drive_c/Games/Control_Resonant"

# List soundbanks and count artbook assets.
python3 resonant_exporter.py --game-root "$GAME" scan

# Validate all 19 music tracks without producing audio files.
python3 resonant_exporter.py --game-root "$GAME" export --dry-run

# Validate just the complete six-track Mixtape.
python3 resonant_exporter.py --game-root "$GAME" export --group mixtape --dry-run

# Export WAV music (no FFmpeg needed).
python3 resonant_exporter.py --game-root "$GAME" export \
  --format wav --output "$HOME/Music/Control-Resonant"

# Export the Deluxe Artbook (PNG plus offline gallery).
python3 resonant_exporter.py --game-root "$GAME" artbook \
  --output "$HOME/Pictures/Control-Resonant"

# List Artbook images without writing them.
python3 resonant_exporter.py --game-root "$GAME" artbook --dry-run

# Optionally retain original extracted DDS assets as well.
python3 resonant_exporter.py --game-root "$GAME" artbook \
  --output "$HOME/Pictures/Control-Resonant" --keep-dds
```

Override the parser location with `--crack /path/to/crack.py`, or the audio decoder via the music command's `--vgmstream /path/to/vgmstream-cli`. `export` also accepts `--group deluxe|mixtape|all|none`, additional `--bank banks/NAME.bnk`, and `--overwrite`. The `music` subcommand is an alias for `export`.

**Storage:** PNG export may require significant temporary disk space. Artbook DDS intermediate files are removed after each image unless `--keep-dds` is selected. The PNGs may still use substantial disk space.

## Test suite

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile resonant_exporter.py
```

Tests use synthetic archive fixtures and stub external tools, not Remedy game assets. An end-to-end smoke test exercises the interactive wizard and output generation. Real-world results can vary with game updates, codecs, and archive layouts; the bundled synthetic tests cannot guarantee compatibility with every version.

## Licensing / distribution

- Original utility code: [MIT License](LICENSE).
- No ownership or redistribution rights to Control Resonant, audio, images, or external software are conferred.
- Third-party binaries/scripts in `tools/` are `.gitignore`d; do **not** commit them, any game archives, or exported art and audio.
- This project is independent and not affiliated with Remedy Entertainment or the game's publishers.
- **See [LEGAL.md](LEGAL.md) before publishing.** A private export test passing does not guarantee the public tool is legal to distribute in every jurisdiction.

---

Made with ❤️ for the Linux Community
