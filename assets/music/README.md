# Bundled Music collection

`catalog.json` lists the eighteen tracks in playback order. Audio and cue filenames
are relative to this directory. Each WAV is mono 22050 Hz signed 16-bit PCM;
the collection is deliberately kept in PCM to avoid codec timing offsets.
The runtime reads only the catalog, WAVs and cue JSON; it downloads nothing.
See [CREDITS.md](CREDITS.md) for source permissions and listening limitations.

## Regeneration

From the repository root, use the pinned isolated `uv` script environment:

```sh
UV_CACHE_DIR=/workspace/.cache/uv uv run --locked scripts/build-music.py
```

The script has its own `scripts/build-music.py.lock`; NumPy 2.2.6 is development
tooling and is not an application dependency. Once the script environment is
available, `uv run --offline --locked scripts/build-music.py` needs no network.
Installed systems ship the committed outputs and never run this tool.

For a comparison without overwriting committed playback assets:

```sh
UV_CACHE_DIR=/workspace/.cache/uv uv run --offline --locked scripts/build-music.py --output build/music-check
```

Compare the generated files to their committed equivalents: eighteen WAVs, eighteen cue
files, the catalog and the build manifest.
Normal regeneration uses the small committed instrument excerpts. To recreate
those excerpts from the original pinned CC0 inputs, the optional maintainer
command below downloads only seven selected WAVs (about 22 MB) into ignored
build storage, verifies every original hash, then prepares and renders:

```sh
UV_CACHE_DIR=/workspace/.cache/uv uv run --locked scripts/build-music.py --fetch-samples --prepare-samples build/music-research/vsco
```

With those original inputs already cached, omit `--fetch-samples` for an offline
preparation check. Full VSCO downloads and an SFZ engine are unnecessary.

Prepared samples retain six seconds, remove only detected pre-onset silence
with a 1 ms margin, average the stereo channels, then average pairs of 44100 Hz
frames for two-tap low-pass decimation to 22050 Hz. Rendering interpolates the
nearest SFZ key-zone sample by semitone ratio, applies attack/velocity/release,
and mixes in float64. A single collection gain caps the maximum at 0.65 if
needed, preserving the score's dynamics and the relative track balance. PCM is
rounded to signed 16-bit with no randomized effects or dither. Sample and
renderer input hashes, gain, output hashes, peaks, RMS, frame counts and event
counts are recorded in the build manifest.

## Formats

The canonical `scores/*.json` use `schema_version: 1`, `id`, `title`,
`tempo_bpm`, `ticks_per_beat: 480` (quarter-note beat), `meter: [numerator,
denominator]`, `intro_ms`, `tail_ms`, an arrangement description, and `notes`.
Each note has integer MIDI `pitch`, `start_tick`, `duration_tick`, `velocity`,
and `voice` (`melody` or `accompaniment`). Start ticks measure from the end of
the intro. Articulation is explicit: most notes release before the next attack;
the final cadence is held for its full value.

Generated cue JSON uses the same event list with `start_ms` and `duration_ms`.
**`start_ms` includes intro silence and measures from the WAV's first frame.**
`duration_ms` at the file's top level is the full decoded WAV duration including
intro and tail. Natural sampled-piano release may sound for up to 600 ms after
the note-off cue; this is distinct from the held-key duration. The catalog's
`duration_ms` equals the cue file's duration exactly, which is generated from
the integer WAV frame count.

## Playable keyboard

`keys/` contains 25 independently prepared C3–C5 two-second PCM notes from the
same CC0 sampled piano. Eight owned SDL channels mix key touches alongside the
unchanged music stream. No synthesis/dependency download occurs during play.
Key release uses a bounded 600 ms quadratic envelope in the event loop;
focus/Home immediately stops held and released voices. Tails occupy channels
until finished; when all eight are busy, a new key replaces the oldest released
tail, never another held key. The keys share a 0.70 channel-gain budget. Existing
voices only become quieter as another key joins, preserving song headroom
(pinned key peaks ≤0.5 and song peaks ≤0.65). No SDL fade-out can override this
budget. Song gain defaults to 1.0. Free Play stops the
song; its keyboard and samples are identical. Preparation:

```sh
uv run --locked scripts/build-music.py --keys-only --output assets/music/keys
```

The key manifest pins instrument/output hashes. This command does not regenerate
or change the song WAVs/cues.

The song list scrolls by touch drag, trackpad or mouse wheel inside its clipped
rail; dragging never selects a song. Free Play, Pause and Autoplay stay pinned.
New songs retain the same two-octave keyboard and soft CC0 piano. Existing six
song WAVs/cues, instrument and playable-key samples remain byte-identical.
