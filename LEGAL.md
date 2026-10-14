# Legal and publication considerations

**As of October 14, 2026 — informational only, not legal advice or a legal release authorization.**

The utility orchestrates locally obtained archive indices, extracts user-selected resources through a separately downloaded `crack.py`, and invokes external conversion tools (`vgmstream-cli` for audio, `ffmpeg` for images and FLAC). It does not include any game data, keys, third-party source code, or decryption implementation.

## Issues to review before publishing on GitHub

- **Effective technical protection measures:** Section 95a of the German Copyright Act (*UrhG*) restricts bypassing effective technological measures and certain circumvention tools. A proprietary resource format alone is not necessarily DRM, but a functioning parser does not prove that protected measures are absent.
- **Private copies:** Section 53 UrhG allows only certain reproductions under specified conditions. Special restrictions may apply to copying substantially complete books, potentially including certain digital artbooks (Section 53(4)). A legitimate game license does not automatically grant the right to distribute the soundtrack or artworks.
- **Software interoperability:** Sections 69d and 69e UrhG provide limited rights to observe and study software and, in some cases, obtain interoperability information. They do not provide blanket permission to republish copyrighted game assets.
- **Contractual terms:** Review the actual game's EULA and the relevant store/license terms and jurisdiction.
- **External parser permissions:** At the time of inspection, the publicly accessible `Control-Resonant-asset-conversion-kit` repository did not display a clear license file. Its source is **not** copied or embedded in this project. Loading separately acquired software at runtime is different from redistributing it; it should still be checked before public promotion.
- **Third-party decoder:** vgmstream is not bundled, and anyone redistributing it must comply with its license. FFmpeg is a separate system dependency with its own licensing obligations.
- **Publication review:** Independently verify the game files' technical protections, store agreements, and relevant law. Seek qualified legal advice if legal certainty is a requirement for launch.

## Project commitments

- Ship only original program code and synthetic tests; never ship soundbanks, WEM, DDS, PNG, or copyrighted media.
- No automatic downloads or game patching; files are read from the user's own installation.
- No attempt to bypass encryption, authentication, copy protection, or entitlement checks.
- Reject output paths inside the game installation.
- Do not claim official status, content ownership, or guaranteed support for all game builds.

## Primary references

- § 95a UrhG: https://www.gesetze-im-internet.de/urhg/__95a.html
- § 53 UrhG: https://www.gesetze-im-internet.de/urhg/__53.html
- § 69d UrhG: https://www.gesetze-im-internet.de/urhg/__69d.html
- § 69e UrhG: https://www.gesetze-im-internet.de/urhg/__69e.html
- External parser: https://github.com/UmFzbXVz/Control-Resonant-asset-conversion-kit
- Decoder downloads: https://vgmstream.org/
- vgmstream license: https://github.com/vgmstream/vgmstream/blob/master/COPYING
