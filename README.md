# Karunaada Kaigannadi — video maker

Turns a topic file into a finished 9:16 Kannada short: AI Kannada voice, real photos from
Wikimedia Commons (free licences, credited on screen), big fact cards, word-group captions,
the channel branding, background music and an end card. Runs free on GitHub Actions.

## One-time setup
1. Create a new GitHub repo, e.g. `karunaada-videos` (Public = unlimited free minutes).
2. Upload everything in this folder, keeping the folders (`assets/`, `scripts/`, `topics/`).
   `.github` is hidden: on GitHub use *Add file → Create new file*, type
   `.github/workflows/make-video.yml` as the name and paste the file's contents.
3. No keys or secrets are needed to make videos.

## Make a video
Actions → **Make Karunaada video** → Run workflow → topic `05`, voice `Suresh` (or `Anu`) → Run.
The first run takes longer (~15–25 min) because it downloads the voice model; later runs reuse it.
When it finishes, open the run and download the zip under **Artifacts**:
- `video.mp4` – the finished short
- `voice.wav` – the narration alone, to judge the voice
- `caption.txt` – caption and hashtags to paste
- `credits.txt` – the photos used and their licences

## The voice
- AI voice: AI4Bharat **Indic Parler-TTS** (Apache-2.0). Kannada voices: Suresh, Anu (recommended), Chetan, Vidya.
- Each phrase is generated separately and re-tried if it comes out too short or too long.
- Want a human voice for a video? Put a recording at `voice/05.m4a` (same number as the topic)
  and run again; it replaces the AI voice automatically.

## Photos that move like camera shots
Each photo fills the whole screen and a "camera" travels across it: wide photos are panned across their
full width; others get a push-in, rise, drift or pull-back. 3D depth from the free Depth Anything V2 Small
model (Apache-2.0) makes near objects move more than the background, like real filming.
Light film grain and a vignette are added. If anything fails, the classic slow zoom is used instead.

## Opening hook
For the first ~3 seconds the hook line appears big in the middle with "ಕೊನೆಯವರೆಗೂ ನೋಡಿ" under it,
over the first 3D camera shot, while the narrator says the opening line.
- Hook text = the first phrase's `card` (or set `"hook": "..."` in the topic file).
- Change or remove the small line with `"hook_sub": "..."` (`""` = none).
Every photo, start to end, is a smooth 3D camera move. Stock clips and the fast opening montage are off
(`USE_STOCK_CLIPS: "1"` / `FAST_OPENING: "1"` in the workflow env turn them back on).

## Adding a topic
Copy `topics/05.json` to a new number and edit:
- `phrases` – one sentence each, in speaking order. `text` is shown as captions; optional
  `say` is what the voice reads (write numbers as Kannada words there, e.g. 1117 → ಸಾವಿರದ ನೂರ ಹದಿನೇಳು). `card` = the big 2–4 word fact card shown
  with that sentence; `shot` = which photo (index in `shots`) plays under it.
- `shots` – Wikimedia Commons search phrases for each photo, best first.
- `caption` – post caption.

## Check before posting
- Listen to every word: AI voices can mispronounce names and numbers. If one is wrong,
  write the number in words in that phrase (e.g. "ಸಾವಿರದ ನೂರ ಹದಿನೇಳು") and run again.
- Look at each photo: Commons search is automatic, so make sure every image really shows the
  right place or sculpture. Change the search words in `shots` if not.

## Local layout test (no internet)
`python scripts/make_video.py --topic 05 --test` – placeholder tone and photos.
