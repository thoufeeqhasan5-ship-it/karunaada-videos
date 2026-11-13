#!/usr/bin/env python3
"""
Karunaada Kaigannadi — makes one Kannada history short (1080x1920 MP4).

  python scripts/make_video.py --topic 05
  python scripts/make_video.py --topic 05 --speaker Anu
  python scripts/make_video.py --topic 05 --test     # no internet: tone instead of voice, placeholder photos

Voice:  AI4Bharat Indic Parler-TTS (Apache-2.0), Kannada speaker Suresh (default) or Anu.
        If a file voice/<topic>.wav or .m4a exists in the repo, that recording is used instead.
Photos: Wikimedia Commons, free licences only, credit shown on screen.
Output: out/video.mp4, out/voice.wav, out/caption.txt, out/credits.txt
"""
import argparse, json, math, os, random, re, shutil, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORK, OUT = ROOT / "work", ROOT / "out"
FPS, W, H = 30, 1080, 1920
LEAD, GAP, END_CARD = 0.45, 0.30, 2.6
UA = {"User-Agent": "KarunaadaKaigannadiBot/1.0 (https://github.com; Kannada heritage shorts)"}
OK_LICENCE = re.compile(r"^(cc0|public domain|pd|cc by(-sa)?( \d\.\d)?( [a-z\-]+)?|cc-by(-sa)?-\d\.\d.*)$", re.I)


def log(*a):
    print("[karunaada]", *a, flush=True)


def run(cmd):
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True)
    if r.returncode:
        log("FAILED:", " ".join(map(str, cmd))[:400]); log(r.stderr[-2500:]); sys.exit(1)
    return r.stdout


def dur(p):
    return float(run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", p]).strip())


# ---------------------------------------------------------------- voice
def expected_seconds(text):
    return max(1.2, len(re.sub(r"\s", "", text)) / 11.5)    # rough Kannada speaking rate


def tts_parler(phrases, speaker, outdir):
    import torch, soundfile as sf
    from parler_tts import ParlerTTSForConditionalGeneration
    from transformers import AutoTokenizer
    torch.set_num_threads(os.cpu_count() or 2)
    name = "ai4bharat/indic-parler-tts"
    log("loading", name)
    model = ParlerTTSForConditionalGeneration.from_pretrained(name).eval()
    tok = AutoTokenizer.from_pretrained(name)
    dtok = AutoTokenizer.from_pretrained(model.config.text_encoder._name_or_path)
    desc = (f"{speaker} speaks in Kannada with a warm, expressive storytelling tone at a moderate pace. "
            f"The recording is very clear and close, with no background noise.")
    d = dtok(desc, return_tensors="pt")
    files = []
    for i, ph in enumerate(phrases):
        text = ph.get("say", ph["text"]).replace("…", ",")   # "say" = numbers written as words
        exp = expected_seconds(text)
        best = None
        for attempt in range(3):
            torch.manual_seed(1234 + attempt * 97)
            p = tok(text, return_tensors="pt")
            t0 = time.time()
            with torch.no_grad():
                g = model.generate(input_ids=d.input_ids, attention_mask=d.attention_mask,
                                   prompt_input_ids=p.input_ids, prompt_attention_mask=p.attention_mask)
            audio = g.cpu().numpy().squeeze()
            raw = outdir / f"raw_{i:02d}_{attempt}.wav"
            sf.write(raw, audio, model.config.sampling_rate)
            clean = outdir / f"p_{i:02d}_{attempt}.wav"
            trim(raw, clean)
            secs = dur(clean)
            ratio = secs / exp
            log(f"phrase {i + 1}/{len(phrases)} try {attempt + 1}: {secs:.1f}s (expected ~{exp:.1f}s) in {time.time() - t0:.0f}s")
            score = abs(math.log(max(ratio, 1e-3)))
            if best is None or score < best[0]:
                best = (score, clean)
            if 0.6 <= ratio <= 1.8:
                break
        final = outdir / f"phrase_{i:02d}.wav"
        shutil.copy(best[1], final)
        files.append(final)
    return files


def trim(src, dst):
    run(["ffmpeg", "-y", "-v", "error", "-i", src, "-af",
         "silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.05,"
         "areverse,silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.08,areverse,"
         "aresample=44100", "-ac", "1", dst])


def tts_test(phrases, outdir):
    files = []
    for i, ph in enumerate(phrases):
        f = outdir / f"phrase_{i:02d}.wav"
        run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
             f"sine=frequency={180 + 20 * (i % 4)}:sample_rate=44100:d={expected_seconds(ph.get('say', ph['text'])):.2f}",
             "-af", "tremolo=f=4:d=0.6,volume=0.4", "-ac", "1", f])
        files.append(f)
    return files


# ---------------------------------------------------------------- photos
def commons_search(query, n=25):
    import requests
    r = requests.get("https://commons.wikimedia.org/w/api.php", headers=UA, timeout=60, params={
        "action": "query", "format": "json", "generator": "search", "gsrsearch": f"{query} filetype:bitmap",
        "gsrnamespace": 6, "gsrlimit": n, "prop": "imageinfo", "iiprop": "url|size|mime|extmetadata",
        "iiurlwidth": 1600})
    r.raise_for_status()
    pages = (r.json().get("query") or {}).get("pages") or {}
    out = []
    for p in sorted(pages.values(), key=lambda x: x.get("index", 99)):
        ii = (p.get("imageinfo") or [{}])[0]
        md = ii.get("extmetadata") or {}
        lic = re.sub(r"<[^>]+>", "", (md.get("LicenseShortName") or {}).get("value", "")).strip()
        artist = re.sub(r"<[^>]+>", "", (md.get("Artist") or {}).get("value", "")).strip()
        if ii.get("mime") not in ("image/jpeg", "image/png") or not OK_LICENCE.match(lic):
            continue
        if min(ii.get("width", 0), ii.get("height", 0)) < 700:
            continue
        out.append({"title": p["title"], "url": ii.get("thumburl") or ii["url"], "licence": lic,
                    "artist": re.sub(r"\s+", " ", artist)[:60] or "Unknown", "page": ii.get("descriptionurl", "")})
    return out


def fetch_photos(shots, outdir):
    import requests
    used, got = set(), []
    for k, s in enumerate(shots):
        chosen = None
        for q in s["q"]:
            try:
                for c in commons_search(q):
                    if c["title"] not in used:
                        chosen = c; break
            except Exception as e:
                log(f"search failed '{q}': {e}")
            if chosen:
                break
        if not chosen:
            log(f"shot {k}: no free photo found, reusing previous")
            got.append(got[-1] if got else None); continue
        used.add(chosen["title"])
        path = outdir / f"photo_{k:02d}.jpg"
        r = requests.get(chosen["url"], headers=UA, timeout=120); r.raise_for_status()
        path.write_bytes(r.content)
        chosen["path"] = path
        log(f"shot {k}: {chosen['title']} ({chosen['licence']}, {chosen['artist']})")
        got.append(chosen)
    return got


def test_photos(shots, outdir):
    from PIL import Image, ImageDraw
    got = []
    for k, _ in enumerate(shots):
        p = outdir / f"photo_{k:02d}.jpg"
        im = Image.new("RGB", (1600, 1100 if k % 2 else 2000), (60 + 20 * k % 160, 40 + 15 * k % 120, 30))
        dr = ImageDraw.Draw(im)
        for i in range(0, 1600, 100):
            dr.line([(i, 0), (i + 600, 2000)], fill=(120, 90, 60), width=6)
        im.save(p, quality=90)
        got.append({"path": p, "title": f"Test photo {k}", "licence": "CC BY-SA 4.0", "artist": "Test", "page": ""})
    return got


# ---------------------------------------------------------------- moving clips for the opening
INTRO_MAX, INTRO_CLIP = 3.6, 0.9      # seconds of quick moving shots at the start, ~0.9 s each


def commons_videos(query, n=15):
    """Free-licence videos from Wikimedia Commons, using a small transcoded copy."""
    import requests
    r = requests.get("https://commons.wikimedia.org/w/api.php", headers=UA, timeout=60, params={
        "action": "query", "format": "json", "generator": "search", "gsrsearch": f"{query} filetype:video",
        "gsrnamespace": 6, "gsrlimit": n, "prop": "videoinfo", "viprop": "url|size|mime|extmetadata|derivatives"})
    r.raise_for_status()
    pages = (r.json().get("query") or {}).get("pages") or {}
    out = []
    for p in sorted(pages.values(), key=lambda x: x.get("index", 99)):
        vi = (p.get("videoinfo") or [{}])[0]
        md = vi.get("extmetadata") or {}
        lic = re.sub(r"<[^>]+>", "", (md.get("LicenseShortName") or {}).get("value", "")).strip()
        artist = re.sub(r"<[^>]+>", "", (md.get("Artist") or {}).get("value", "")).strip()
        if not OK_LICENCE.match(lic) or float(vi.get("duration") or 0) < 3:
            continue
        ders = [d for d in (vi.get("derivatives") or []) if "webm" in d.get("type", "") and 360 <= int(d.get("height") or 0) <= 1080]
        ders.sort(key=lambda d: abs(int(d.get("height") or 0) - 720))
        url = ders[0]["src"] if ders else (vi.get("url") if (vi.get("size") or 0) < 80_000_000 else None)
        if not url:
            continue
        out.append({"title": p["title"], "url": url, "licence": lic, "artist": re.sub(r"\s+", " ", artist)[:60] or "Unknown",
                    "page": vi.get("descriptionurl", ""), "duration": float(vi.get("duration") or 0)})
    return out


def pixabay_videos(query, n=8):
    """Pixabay stock clips (free, no attribution needed). Only if the secret PIXABAY_KEY is set."""
    import requests
    key = os.getenv("PIXABAY_KEY", "").strip()
    if not key:
        return []
    r = requests.get("https://pixabay.com/api/videos/", timeout=60,
                     params={"key": key, "q": query[:100], "per_page": n, "safesearch": "true"})
    r.raise_for_status()
    out = []
    for h in r.json().get("hits", []):
        v = (h.get("videos") or {}).get("medium") or (h.get("videos") or {}).get("small") or {}
        if v.get("url") and (h.get("duration") or 0) >= 3:
            out.append({"title": f"Pixabay video {h.get('id')}", "url": v["url"], "licence": "Pixabay Content License",
                        "artist": h.get("user") or "Pixabay", "page": h.get("pageURL", ""), "duration": float(h.get("duration") or 0),
                        "pixabay": True})
    return out


def motion_queries(topic):
    """Topic can set "motion": [...]; otherwise use its photo searches and English title."""
    if topic.get("motion"):
        return list(topic["motion"])
    qs = [topic.get("title_en", "")] + [q for s in topic.get("shots", []) for q in s.get("q", [])[:1]]
    return [q for q in dict.fromkeys(q.strip() for q in qs) if q]


def fetch_motion(topic, outdir, want=4):
    import requests
    found, seen = [], set()
    queries = motion_queries(topic)
    sources = [(commons_videos, q) for q in queries] + \
              [(pixabay_videos, q) for q in queries] + [(pixabay_videos, f"{topic.get('title_en', '')} India")]
    for fn, q in sources:
        if len(found) >= want:
            break
        try:
            for c in fn(q):
                if c["url"] in seen:
                    continue
                seen.add(c["url"])
                path = outdir / f"motion_src_{len(found):02d}{Path(c['url'].split('?')[0]).suffix or '.mp4'}"
                r = requests.get(c["url"], headers=UA, timeout=180); r.raise_for_status()
                path.write_bytes(r.content)
                c["path"] = path
                found.append(c)
                log(f"motion clip {len(found)}: {c['title']} ({c['licence']}, {c['artist']}) from '{q}'")
                if len(found) >= want:
                    break
        except Exception as e:
            log(f"motion search failed '{q}': {str(e)[:150]}")
    return found


def test_motion(outdir, want=4):
    got = []
    for k in range(want):
        p = outdir / f"motion_src_{k:02d}.mp4"
        run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc2=size=1280x720:rate=30:d=6",
             "-vf", f"hue=h={k * 70}", "-c:v", "libx264", "-preset", "veryfast", p])
        got.append({"path": p, "title": f"Test clip {k}", "licence": "CC BY 4.0", "artist": "Test", "page": "", "duration": 6})
    return got


def motion_clip(src, seconds, idx, dst):
    """A short moving shot: random start, cropped to 9:16, a slight push-in, a little punchier colour."""
    total = float(src.get("duration") or 0) or dur(src["path"])
    start = max(0.0, min(total - seconds - 0.2, 1.0 + random.Random(idx).random() * max(0.0, total - seconds - 2.0)))
    n = max(1, int(round(seconds * FPS)))
    run(["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.2f}", "-i", src["path"], "-t", f"{seconds + 0.1:.2f}", "-an",
         "-vf", f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={FPS},"
                f"scale=w='trunc({W}*(1+0.06*t/{seconds:.2f})/2)*2':h=-2:eval=frame,crop={W}:{H},"
                "eq=contrast=1.08:saturation=1.12,format=yuv420p",
         "-frames:v", n, "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-r", FPS, dst])


def quick_photo(still, seconds, idx, dst):
    """Backup opening shot when no video clips exist: a fast punch-in or sweep across a real photo."""
    n = max(1, int(round(seconds * FPS)))
    mode = idx % 4
    if mode == 0:      # fast punch-in to the centre
        z, x, y = f"1.0+0.30*on/{n}", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    elif mode == 1:    # sweep left -> right
        z, x, y = "1.25", f"(iw-iw/zoom)*on/{n}", "ih/2-(ih/zoom/2)"
    elif mode == 2:    # pull back out
        z, x, y = f"1.32-0.30*on/{n}", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    else:              # tilt up
        z, x, y = "1.25", "iw/2-(iw/zoom/2)", f"(ih-ih/zoom)*(1-on/{n})"
    run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-i", still, "-vf",
         f"scale={W * 2}:{H * 2},zoompan=z='{z}':x='{x}':y='{y}':d={n}:s={W}x{H}:fps={FPS},"
         "eq=contrast=1.06:saturation=1.1,format=yuv420p",
         "-frames:v", n, "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", dst])


def compose_still(src, dst):
    """Photo fitted over a blurred copy of itself, 1080x1920."""
    from PIL import Image, ImageFilter, ImageEnhance
    im = Image.open(src).convert("RGB")
    bg = im.copy()
    s = max(W / bg.width, H / bg.height)
    bg = bg.resize((math.ceil(bg.width * s), math.ceil(bg.height * s)))
    bg = bg.crop(((bg.width - W) // 2, (bg.height - H) // 2, (bg.width - W) // 2 + W, (bg.height - H) // 2 + H))
    bg = ImageEnhance.Brightness(bg.filter(ImageFilter.GaussianBlur(40))).enhance(0.55)
    ratio = im.width / im.height
    if ratio < 0.75:                       # tall photo: fill the frame
        fg = im.resize((math.ceil(im.width * s), math.ceil(im.height * s)))
        fg = fg.crop(((fg.width - W) // 2, (fg.height - H) // 2, (fg.width - W) // 2 + W, (fg.height - H) // 2 + H))
        bg = fg
    else:                                  # wide photo: fit width, centred
        fs = min(W / im.width, 1250 / im.height)
        fg = im.resize((int(im.width * fs), int(im.height * fs)))
        bg.paste(fg, ((W - fg.width) // 2, (H - fg.height) // 2 - 60))
    bg.save(dst, quality=92)


# ---------------------------------------------------------------- photo -> "camera shot" (2.5D parallax)
_depth_model = None
_depth_cache = {}


def depth_map(img_bgr, key, test=False):
    """How near each pixel is (0 = far, 1 = near), same size as the image. Depth Anything V2 Small (Apache-2.0)."""
    import numpy as np, cv2
    if key in _depth_cache:
        return _depth_cache[key]
    h, w = img_bgr.shape[:2]
    d = None
    if test:     # synthetic depth for offline tests: lower part and centre are nearer
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        d = 0.6 * (yy / h) + 0.4 * np.exp(-(((xx - w / 2) / (w * 0.2)) ** 2 + ((yy - h * 0.6) / (h * 0.2)) ** 2))
    else:
        global _depth_model
        if _depth_model is not False:
            try:
                from PIL import Image
                if _depth_model is None:
                    from transformers import pipeline
                    _depth_model = pipeline("depth-estimation", model="depth-anything/Depth-Anything-V2-Small-hf", device=-1)
                    log("depth model loaded")
                out = _depth_model(Image.fromarray(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)))
                d = np.asarray(out["depth"].convert("L").resize((w, h)), dtype=np.float32)
            except Exception as e:
                log(f"depth unavailable ({str(e)[:160]}), camera moves without 3D depth")
                _depth_model = False
    if d is None:
        d = np.zeros((h, w), np.float32)
    else:
        lo, hi = np.percentile(d, 2), np.percentile(d, 98)
        d = np.clip((d - lo) / max(1e-6, hi - lo), 0, 1)
        d = cv2.GaussianBlur(d, (0, 0), max(3, w / 160))    # soft edges = no tearing around objects
    _depth_cache[key] = d
    return d


def camera_shot(photo, seconds, idx, dst, test=False, fast=False):
    """Turn a photo into a filmed-looking shot: the photo fills the screen and a 'camera' travels across it
    (pan / push-in / rise), with 3D parallax - near things move more than the background."""
    import numpy as np, cv2
    try:
        src = cv2.imread(str(photo))
        if src is None:
            raise RuntimeError("cannot read photo")
        # canvas: photo scaled to fill the 9:16 frame with room to move (wide photos stay wide for panning)
        sc = max(W * 1.18 / src.shape[1], H * 1.18 / src.shape[0])
        cw, ch = int(src.shape[1] * sc), int(src.shape[0] * sc)
        if cw > W * 3.2:                                     # very wide panoramas: keep the middle part
            x0 = (cw - int(W * 3.2)) // 2
        else:
            x0 = 0
        canvas = cv2.resize(src, (cw, ch), interpolation=cv2.INTER_AREA if sc < 1 else cv2.INTER_CUBIC)
        if x0:
            canvas = np.ascontiguousarray(canvas[:, x0:x0 + int(W * 3.2)])
        ch, cw = canvas.shape[:2]
        D = depth_map(canvas, f"{photo}", test)

        n = max(1, int(round(seconds * FPS)))
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        ox, oy = xx - W / 2.0, yy - H / 2.0
        wide = cw > W * 1.6
        room_x, room_y = (cw - W) / 2.0, (ch - H) / 2.0       # how far the view can travel from the centre
        if wide:
            mode = ["pan_r", "pan_l", "pan_r_in"][idx % 3]
        else:
            mode = ["push", "rise", "push_side", "pull"][idx % 4]
        amp = 1.6 if fast else 1.0
        proc = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}",
                                 "-r", str(FPS), "-i", "-", "-vf", "format=yuv420p", "-c:v", "libx264", "-preset", "veryfast",
                                 "-crf", "19", str(dst)], stdin=subprocess.PIPE)
        for f in range(n):
            p = f / max(1, n - 1)
            e = p * p * (3 - 2 * p)                          # ease in/out, like a camera operator
            zoom, cx, cy, par_x, par_y, dz = 1.0, cw / 2.0, ch / 2.0, 0.0, 0.0, 0.0
            if mode in ("pan_r", "pan_l", "pan_r_in"):       # travel across a wide photo
                dirn = -1 if mode == "pan_l" else 1
                cx = cw / 2.0 + dirn * (-1 + 2 * e) * room_x * 0.92
                zoom = 1.0 + (0.10 * e if mode == "pan_r_in" else 0.0)
                par_x = dirn * (-1 + 2 * e) * 0.07 * W * amp     # near objects slide past faster
            elif mode == "push":                             # dolly in: near objects grow faster
                zoom, dz = 1.0 + 0.16 * e * amp, 0.18 * e * amp
            elif mode == "rise":                             # crane up
                cy = ch / 2.0 + (1 - 2 * e) * room_y * 0.9
                par_y = (1 - 2 * e) * 0.06 * H * amp
                zoom = 1.04
            elif mode == "push_side":                        # push in while drifting sideways
                zoom, dz = 1.0 + 0.12 * e * amp, 0.12 * e * amp
                cx = cw / 2.0 + (-1 + 2 * e) * room_x * 0.8
                par_x = (-1 + 2 * e) * 0.05 * W * amp
            else:                                            # pull back: reveal
                zoom, dz = 1.18 - 0.16 * e, 0.18 * (1 - e)
            # where each output pixel looks in the canvas (without depth), then add the depth effect
            bx = cx + ox / zoom
            by = cy + oy / zoom
            Dv = cv2.remap(D, bx, by, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
            s3 = 1.0 + dz * Dv
            mapx = cx + ox / (zoom * s3) - par_x * Dv / zoom
            mapy = cy + oy / (zoom * s3) - par_y * Dv / zoom
            frame = cv2.remap(canvas, mapx, mapy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
            proc.stdin.write(frame.tobytes())
        proc.stdin.close()
        if proc.wait() != 0:
            raise RuntimeError("ffmpeg failed while writing the camera move")
        return
    except Exception as e:
        log(f"camera move failed ({str(e)[:160]}), using a slow zoom")
    still = Path(str(dst) + ".jpg")
    compose_still(photo, still)
    kenburns(still, seconds, idx, dst)


def kenburns(still, seconds, idx, dst):
    n = max(1, int(round(seconds * FPS)))
    zin = idx % 2 == 0
    z = f"min(1.0+0.10*on/{n},1.10)" if zin else f"max(1.10-0.10*on/{n},1.0)"
    run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-i", still, "-vf",
         f"scale={W * 2}:{H * 2},zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={n}:s={W}x{H}:fps={FPS},format=yuv420p",
         "-frames:v", n, "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", dst])


# ---------------------------------------------------------------- timeline
def caption_chunks(text, start, end, max_words=3):
    words = text.split()
    chunks = [" ".join(words[i:i + max_words]) for i in range(0, len(words), max_words)]
    if len(chunks) > 1 and len(chunks[-1].split()) == 1:
        last = chunks.pop()
        chunks[-1] += " " + last
    total = sum(len(c) for c in chunks)
    out, t = [], start
    for c in chunks:
        d = (end - start) * len(c) / total
        out.append({"text": c, "start": round(t, 3), "end": round(t + d, 3)})
        t += d
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--topic", required=True)
    ap.add_argument("--speaker", default=os.getenv("SPEAKER", "Suresh"))
    ap.add_argument("--test", action="store_true")
    a = ap.parse_args()
    topic = json.loads((ROOT / "topics" / f"{a.topic}.json").read_text(encoding="utf-8"))
    shutil.rmtree(WORK, ignore_errors=True); WORK.mkdir(parents=True); OUT.mkdir(exist_ok=True)
    phrases, shots = topic["phrases"], topic["shots"]

    # 1. voice
    own = next((ROOT / "voice" / f"{a.topic}{ext}" for ext in (".wav", ".m4a", ".mp3")
                if (ROOT / "voice" / f"{a.topic}{ext}").exists()), None)
    if own:
        log("using your own recording:", own.name)
        files = None
    else:
        files = tts_test(phrases, WORK) if a.test else tts_parler(phrases, a.speaker, WORK)

    # 2. timeline + voice track
    t, segs, parts = LEAD, [], []
    if files:
        for ph, f in zip(phrases, files):
            d = dur(f)
            segs.append((t, t + d))
            parts.append((f, t))
            t += d + GAP + float(ph.get("pause_after", 0))
        voice_end = segs[-1][1]
        inputs, filt = [], []
        for i, (f, st) in enumerate(parts):
            inputs += ["-i", f]
            filt.append(f"[{i}:a]adelay={int(st * 1000)}|{int(st * 1000)}[v{i}]")
        filt.append("".join(f"[v{i}]" for i in range(len(parts))) +
                    f"amix=inputs={len(parts)}:normalize=0,apad=whole_dur={voice_end + 0.2:.2f},"
                    "loudnorm=I=-15:TP=-1.5:LRA=11[out]")
        run(["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", ";".join(filt), "-map", "[out]",
             "-ar", "44100", "-ac", "2", OUT / "voice.wav"])
    else:
        # own recording: spread phrases by text length over its duration
        run(["ffmpeg", "-y", "-v", "error", "-i", own, "-af",
             "silenceremove=start_periods=1:start_threshold=-45dB,loudnorm=I=-15:TP=-1.5:LRA=11",
             "-ar", "44100", "-ac", "2", WORK / "own.wav"])
        total = dur(WORK / "own.wav")
        run(["ffmpeg", "-y", "-v", "error", "-i", WORK / "own.wav", "-af", f"adelay={int(LEAD * 1000)}:all=1",
             OUT / "voice.wav"])
        lens = [len(p["text"]) for p in phrases]
        for L in lens:
            d = total * L / sum(lens)
            segs.append((t, t + d)); t += d
        voice_end = segs[-1][1]
    end_start = voice_end + 0.5
    total_dur = end_start + END_CARD

    # 3. photos and shots
    photos = test_photos(shots, WORK) if a.test else fetch_photos(shots, WORK)
    shot_start = {}
    for i, ph in enumerate(phrases):
        shot_start.setdefault(ph.get("shot", 0), segs[i][0] if i else 0.0)
    order = sorted(shot_start.items(), key=lambda kv: kv[1])
    clips, credits = [], []

    # 3a. opening: 3-4 quick moving shots before the first photo (if any free clips are found)
    # Stock video clips are OFF: they rarely show the actual place. Every shot is a real photo of it,
    # turned into a 3D camera move. (Set USE_STOCK_CLIPS=1 to try Wikimedia/Pixabay clips again.)
    if a.test:
        motion = test_motion(WORK) if os.getenv("TEST_CLIPS") else []
    else:
        motion = fetch_motion(topic, WORK) if os.getenv("USE_STOCK_CLIPS") == "1" else []
    first_len = (order[1][1] if len(order) > 1 else end_start) - order[0][1]
    intro = 0.0
    fast_opening = os.getenv("FAST_OPENING") == "1"   # off: open straight on the first 3D camera shot
    if len(motion) >= 2:
        intro = min(INTRO_MAX, first_len if first_len - INTRO_MAX < 0.8 else INTRO_MAX)
        n_cl = max(2, min(len(motion), round(intro / INTRO_CLIP)))
        t_cl = 0.0
        for m in range(n_cl):
            seg = round(intro / n_cl, 3) if m < n_cl - 1 else round(intro - t_cl, 3)
            clip = WORK / f"intro_{m:02d}.mp4"
            motion_clip(motion[m], seg, m, clip)
            clips.append(clip)
            src = motion[m]
            credits.append({"text": ("Video: Pixabay" if src.get("pixabay") else
                                     f"Video: {src['artist']} · {src['licence']} · Wikimedia Commons") if not a.test else "Video: test",
                            "start": round(t_cl, 3), "end": round(t_cl + seg, 3)})
            t_cl += seg
        log(f"opening: {n_cl} moving shots, {intro:.1f}s")
    elif fast_opening:
        # optional: fast moves across the real photos
        motion = []
        pics = []
        for p in photos:                      # unique photos, in shot order
            if p and all(p is not q for q in pics):
                pics.append(p)
        if pics:
            intro = min(INTRO_MAX, first_len if first_len - INTRO_MAX < 0.8 else INTRO_MAX)
            n_cl = max(3, round(intro / INTRO_CLIP))
            t_cl = 0.0
            for m in range(n_cl):
                p = pics[m % len(pics)]
                seg = round(intro / n_cl, 3) if m < n_cl - 1 else round(intro - t_cl, 3)
                clip = WORK / f"intro_{m:02d}.mp4"
                camera_shot(p["path"], seg, m, clip, a.test, fast=True)
                clips.append(clip)
                credits.append({"text": f"Photo: {p['artist']} · {p['licence']} · Wikimedia Commons" if not a.test else "Photo: test",
                                "start": round(t_cl, 3), "end": round(t_cl + seg, 3)})
                t_cl += seg
            log(f"opening: {n_cl} fast 3D camera moves over the real photos, {intro:.1f}s")
        else:
            log("opening: no photos for fast moves, starting with the photo")
    else:
        motion = []
        log("opening: hook screen over the first 3D camera shot")

    for j, (k, st) in enumerate(order):
        en = order[j + 1][1] if j + 1 < len(order) else end_start
        if j == 0 and intro:
            st = intro
            if en - st < 0.3:           # the whole first slot went to the moving shots
                continue
        p = photos[k] if k < len(photos) else None
        if p is None:
            p = next((x for x in photos if x), None)
        clip = WORK / f"clip_{j:02d}.mp4"
        camera_shot(p["path"], en - st, j, clip, a.test)
        clips.append(clip)
        credits.append({"text": f"Photo: {p['artist']} · {p['licence']} · Wikimedia Commons" if not a.test else "Photo: test",
                        "start": round(st, 3), "end": round(en, 3)})
    # end card background (black) is drawn by the overlay
    lst = WORK / "clips.txt"
    lst.write_text("".join(f"file '{c}'\n" for c in clips))
    # light film grain + vignette: reads as filmed footage rather than a slideshow
    run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", lst, "-r", FPS,
         "-vf", "noise=c0s=7:c0f=t+u,vignette=angle=PI/5",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-pix_fmt", "yuv420p", WORK / "photos.mp4"])

    # 4. overlay timeline
    cards, caps = [], []
    for i, ph in enumerate(phrases):
        st, en = segs[i]
        if ph.get("card"):
            cards.append({"text": ph["card"], "start": round(st, 3), "end": round(min(en + 0.6, end_start), 3)})
        caps += caption_chunks(ph["text"], st, en)
    # hook screen: the opening line, big in the middle, for the first ~3 s
    first_end = min(order[1][1] if len(order) > 1 else end_start, 3.2)
    hook_text = topic.get("hook") or topic["phrases"][0].get("card") or topic.get("title_kn", "")
    hook = {"text": hook_text, "sub": topic.get("hook_sub", "ಕೊನೆಯವರೆಗೂ ನೋಡಿ"),
            "start": 0.0, "end": round(max(2.2, first_end), 3)}
    cards = [c for c in cards if c["start"] >= hook["end"] - 0.05]   # no small card under the hook
    data = {"endStart": round(end_start, 3), "cards": cards, "caps": caps, "credits": credits, "hook": hook}
    frames = WORK / "frames"; frames.mkdir()
    render_overlay(data, total_dur, frames)

    # 5. final mix
    music = ROOT / "assets" / "music.m4a"
    fo = max(0, total_dur - 1.0)
    run(["ffmpeg", "-y", "-v", "error",
         "-stream_loop", "-1", "-i", WORK / "photos.mp4",
         "-framerate", FPS, "-i", frames / "%05d.png",
         "-i", OUT / "voice.wav",
         "-stream_loop", "-1", "-i", music,
         "-filter_complex",
         f"[0:v]tpad=stop_mode=clone:stop_duration=5[bg];[bg][1:v]overlay=0:0:format=auto,format=yuv420p,"
         f"fade=t=out:st={fo:.2f}:d=1[v];"
         f"[3:a]volume=0.16,afade=t=in:d=1,afade=t=out:st={fo:.2f}:d=1[m];"
         f"[2:a]apad[vo];[vo][m]amix=inputs=2:normalize=0:duration=first,alimiter=limit=0.9[a]",
         "-map", "[v]", "-map", "[a]", "-t", f"{total_dur:.3f}", "-r", FPS,
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac", "-b:a", "160k",
         "-movflags", "+faststart", OUT / "video.mp4"])

    (OUT / "caption.txt").write_text(topic.get("caption", ""), encoding="utf-8")
    (OUT / "credits.txt").write_text("\n".join(
        f"{p['title']} — {p['artist']} — {p['licence']} — {p['page']}" for p in list(motion) + [x for x in photos if x]),
        encoding="utf-8")
    log(f"done: out/video.mp4 ({total_dur:.1f}s), voice: {'own recording' if own else a.speaker}")


def render_overlay(data, total, frames):
    from playwright.sync_api import sync_playwright
    n = int(math.ceil(total * FPS))
    prev, prevf, uniq, t0 = None, None, 0, time.time()
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        pg = b.new_page(viewport={"width": W, "height": H})
        pg.goto((ROOT / "scripts" / "overlay.html").as_uri())
        pg.evaluate("d => setup(d)", data)
        pg.evaluate("document.fonts.ready"); pg.wait_for_timeout(300)
        stage = pg.locator("#stage")
        for f in range(n):
            key = pg.evaluate("t => render(t)", f / FPS)
            out = frames / f"{f:05d}.png"
            if key == prev:
                os.link(prevf, out)
            else:
                stage.screenshot(path=str(out), omit_background=True); prev, prevf = key, out; uniq += 1
        b.close()
    log(f"overlay: {uniq} unique of {n} frames in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
