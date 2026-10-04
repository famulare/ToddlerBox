# Music sources and credits

The compositions, source editions, instrument recordings, and new arrangements
are distinct. All eighteen playback files are newly rendered instrumental piano
arrangements for ToddlerBox. No third-party finished recording is included.
Source files/records and SHA-256 hashes are retained in `sources/manifest.json`.
The new score events and accompaniment are in `scores/*.json`; playback and cue
hashes are in `build-manifest.json`.

| Track | Composition and source | Permission and changes |
| --- | --- | --- |
| Mary Had a Little Lamb | Traditional familiar melody. Verified against Giles F. Hall's `mary.mid` and note-event fixture in [python-midi](https://github.com/vishnubob/python-midi/tree/3fe5d295edb18ee211e163cb8369f4c3e691e418), revision `3fe5d295edb18ee211e163cb8369f4c3e691e418`. | Upstream **MIT**, copyright 2013 Giles F. Hall; complete notice in `licenses/Mary-MIT.txt`. Extract the 26 melody notes; replace accompaniment, dynamics, articulation and tempo. The familiar E–D–C opening is checked against the preserved fixture. This does not use the unverified historical 1831 setting. |
| Twinkle, Twinkle, Little Star | Traditional French melody *Ah! vous dirai-je, maman*, used by Wolfgang Amadeus Mozart in K.265. Theme reference: [Mutopia 2236](https://www.mutopiaproject.org/cgibin/piece-info.cgi?id=2236), guitar edition by J. J. Olson, `Mutopia-2018/12/07-2236`. | Source edition explicitly **Public Domain** in retained LilyPond header. Complete familiar theme, omit ornaments and guitar texture, sustain phrase endings, add sparse roots and two quiet fifths. |
| Ode to Joy | Ludwig van Beethoven. [Mutopia 528](https://www.mutopiaproject.org/cgibin/piece-info.cgi?id=528), Peter Chubb, `Mutopia-2009/08/05-528`. | Source edition explicitly **Public Domain**. Opening eight soprano bars, transposed G to C, replace SATB parts with sparse piano roots. |
| Frère Jacques | Traditional French round. [Mysid's notation](https://commons.wikimedia.org/wiki/File:Fr%C3%A8re_Jacques.svg), uploaded 2012-01-05 00:08:40 UTC; metadata retained, file page revision `1038864400`. | Mysid's notation record explicitly **CC0**. One complete familiar melody, no overlapping round, new sparse accompaniment. The file's license metadata was verified; an image download was unavailable in this environment, so the transcription uses the familiar traditional melody rather than claiming a visual comparison with the source image. |
| Row, Row, Row Your Boat | Traditional nursery song. [Mysid's notation](https://commons.wikimedia.org/wiki/File:Row_your_boat.svg), uploaded 2012-01-04 23:39:13 UTC; metadata retained. | Mysid's notation record explicitly **CC0**. Two complete verses in compound rhythm, one melody voice, new sparse accompaniment. The license metadata was verified; the source image download was unavailable, so no visual comparison is claimed. |
| Minuet in G, BWV Anh.114 | **Christian Petzold**, formerly attributed to J. S. Bach. [Mutopia 75](https://www.mutopiaproject.org/cgibin/piece-info.cgi?id=75), Allen Garvin, `Mutopia-2017/01/19-75`, Bach-Gesellschaft source. | Source edition explicitly **Public Domain**. Complete opening 16-bar section played once; transpose the whole section from G to C, omit ornaments/grace note, simplify bass. Title identifies the original composition; this recording is in C major. |

## Piano

**VSCO 2 Community Edition**, [SFZ repository](https://github.com/sgossner/VSCO-2-CE/tree/6dd651d55dde97fd4028699be9d4481f26917891),
revision `6dd651d55dde97fd4028699be9d4481f26917891`, **CC0 1.0**.
The complete upstream license is in `licenses/VSCO-CC0.txt`.
Credit **Versilian Studios / Sam Gossner**, **Ivy Audio / Simon Dalzell**, and
sample cutting **Elan Hickler / Soundemote**. The README requests credit where
applicable; ToddlerBox retains all named recording/cutting contributors.

Only seven soft-layer upright-piano samples from `UprightPiano.sfz` are used:
`Player_dyn1_rr1_014`, `016`, `018`, `020`, `022`, `024`, `026`.
The original mapping and README are retained under `sources/`. Exact sample
URLs, original hashes, prepared hashes, key centers and trim amounts are in
`instrument/manifest.json`. The bundled prepared samples are six-second mono
22050 Hz PCM excerpts of the CC0 recordings. They remain CC0 source material.

The offline renderer is a deliberately bounded sampler, rather than a complete
SFZ implementation. It uses the selected soft-layer key zones, tuning and
23 dB source gain, a 1 ms attack, squared velocity gain, linear interpolation,
and a 600 ms cosine-squared release. It does not synthesize piano at runtime.

New ToddlerBox arrangements, rendered performances and renderer contributions
are distributed under the project's **MIT License**, copyright 2026 Mike
Famulare, retained in `licenses/ToddlerBox-MIT.txt` and the repository `LICENSE`.
Third-party permissions listed here apply to their respective source material;
the CC0 piano inputs and the additional MIT Mary notice remain identified.

## Checks and listening

Each arrangement uses MIDI pitches C3–C5 (48–72), a constant tempo, explicit
1500 ms intro and 1500 ms tail, and at most three simultaneous score notes.
Decoded WAV checks establish non-silence, no clipping, complete quiet endings,
onset within 50 ms of the first cue, and exact score/cue/frame duration agreement.
An offline rebuild checks identical output hashes. These checks establish file
properties and timing, **not a person's listening approval**. A person still
needs to listen for timbre, correct phrasing, balance and suitable volume on the
VM/HP playback path. Speaker loudness and physical output latency remain
hardware qualification work.


## 0.4 expansion

Twelve additional short arrangements use historical melodies, with no imported
finished recordings, modern lyrics or modern accompaniment. The traditional
melodies are Hot Cross Buns, London Bridge, Itsy Bitsy Spider, Old MacDonald,
This Old Man, Hickory Dickory Dock, Pop Goes the Weasel, Bingo and Mulberry Bush.
These are historical/traditional tunes, not recordings of recent commercial
children's versions. New note events, sparse roots and piano performances are
ToddlerBox MIT contributions; original six outputs remain unchanged.

The classical motifs are Brahms's *Wiegenlied*, Op.49 No.4 (1868), Grieg's
*Morning Mood* from *Peer Gynt* (1875; Suite Op.46), and Dvořák's Symphony No.9,
Op.95 second-movement Largo (1893). These compositions are public domain; the
Largo follows the instrumental theme, not the later *Goin' Home* song arrangement.
All three are transposed to C and use simple sparse accompaniment. Morning Mood
keeps its compound-meter contour with a slower pulse. Lullaby's pickup/dotted
rhythm and Weasel's jig quarter/eighth pairs have source-grounded fixtures.

Brahms reference: pinned Mutopia public-domain LilyPond score retained as
`sources/lullaby.ly`, crediting its Indiana University source. Weasel reference:
John B. Walsh's ABC transcription of the historical jig (Coles p.24.6), retained
as `sources/weasel.abc` from music21. The traditional composition is public domain;
the repository BSD-3-Clause notice is retained in `licenses/music21-BSD.txt`.
Exact source revisions, URLs and SHA-256 hashes are in `sources/manifest.json`.
The sources establish reference facts, not approval of the simplified arrangement.
Manual listening on the HP remains necessary for phrasing, timbre and comfort.
