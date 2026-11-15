# juno_rostproxy.py — Röstproxy (Fas 3.6, JUNO_RÖST_SPEC §12 + ROSTPROXY_VAD_STT_KRAVLISTA)
#
# OpenAI-kompatibla endpoints som OW pekar på som STT/TTS-engine:
#   POST /v1/audio/speech          → TTS: Edge TTS sv-SE (primär) → Kokoro en (fallback) → WebAPI (reserv)
#   POST /v1/audio/transcriptions  → STT: faster-whisper + VAD + hallucination-filter (P9)
#   GET  /health                   → status
#
# Regler (kravlistan §1): startas på-begäran via start_rostproxy.ps1, ALDRIG autostart;
# allt loggas till audit + felrapport (Regel 43); inga hemligheter i kod (Regel 39);
# endast localhost-bindning (127.0.0.1:8765).
#
# Kör: python juno_core/services/juno_rostproxy.py  (eller via start_rostproxy.ps1)

from __future__ import annotations

import asyncio
import io
import json
import os
import re
import statistics
import tempfile
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# ---------------------------------------------------------------- config (kravlistan §3)
CONFIG = {
    "vad": {
        "sample_rate": 16000,
        "chunk_ms": 30,
        "speech_confirm_ms": 300,
        "silence_duration_s": 3.0,
        "no_speech_timeout_s": 15.0,
        "calibration_ms": 1000,
        "barge_in_grace_s": 0.5,
        "barge_in_threshold_multiplier": 3.0,
        "abs_min_rms": 200,
    },
    "stt": {
        "provider": os.getenv("JUNO_STT_PROVIDER", "groq"),  # "groq" (moln, ~0.3 s) | "local" (faster-whisper)
        "groq_model": os.getenv("JUNO_STT_GROQ_MODEL", "whisper-large-v3-turbo"),
        "model": os.getenv("JUNO_STT_MODEL", "base"),
        "language": "sv",
        "beam_size": 1,
        "compute_type": "int8",
        "cpu_threads": 4,
        "condition_on_previous_text": False,
    },
    "llm": {
        "groq_model": os.getenv("JUNO_LLM_GROQ_MODEL", "openai/gpt-oss-20b"),
    },
    "tts": {
        "edge_voice_sv": os.getenv("JUNO_TTS_EDGE_VOICE_SV", "sv-SE-SofieNeural"),
        "kokoro_voice_en": os.getenv("JUNO_TTS_KOKORO_VOICE_EN", "af_heart"),
        "fallback_webapi": True,
    },
}
HOST = "127.0.0.1"
PORT = int(os.getenv("JUNO_ROSTPROXY_PORT", "8765"))
LOGS_DIR = PROJECT_ROOT / "logs" / "rostproxy"
RÖSTVAL_FIL = LOGS_DIR / "röstval.json"
LIVEFEED_PATH = Path(os.getenv("JUNO_LIVEFEED_LOG", PROJECT_ROOT / "logs" / "livefeed.log"))


def _livefeed(nivå: str, msg: str) -> None:
    """Skriver en rad till livefeed (formatet '<ISO-ts> | <nivå> | rost | <msg>' — samma som juno_livefeed)."""
    try:
        LIVEFEED_PATH.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with LIVEFEED_PATH.open("a", encoding="utf-8") as fh:
            fh.write(f"{ts} | {nivå} | rost | {msg[:300]}\n")
    except Exception:
        pass

# ---------------------------------------------------------------- röstlista (röstväljaren)
# Edge sv-SE (2 röster — verifierat via edge_tts.list_voices()) + Kokoro engelska som tillval.
VOICES = [
    {"id": "sv-SE-SofieNeural", "namn": "Sofie (svenska)", "kön": "Kvinna", "motor": "Edge TTS"},
    {"id": "sv-SE-MattiasNeural", "namn": "Mattias (svenska)", "kön": "Man", "motor": "Edge TTS"},
    {"id": "kokoro-af_heart", "namn": "Heart (engelska, Kokoro)", "kön": "Kvinna", "motor": "Kokoro fallback"},
]


def _läs_röstval() -> str:
    """Aktiv röst från state-filen (fallback: env-default sv-SE-SofieNeural)."""
    try:
        if RÖSTVAL_FIL.exists():
            return json.loads(RÖSTVAL_FIL.read_text(encoding="utf-8")).get("voice", "")
    except Exception:
        pass
    return ""


def _spara_röstval(voice: str) -> None:
    try:
        RÖSTVAL_FIL.parent.mkdir(parents=True, exist_ok=True)
        RÖSTVAL_FIL.write_text(
            json.dumps({"voice": voice, "uppdaterad": datetime.now(timezone.utc).isoformat(timespec="seconds")},
                       ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        _felrapport("spara_röstval", str(exc))


def _ow_token() -> str:
    """OW-admin-token (Regel 39): miljövariabel ELLER ow_admin_token.txt — aldrig i kod."""
    p = Path(os.getenv("OW_ADMIN_TOKEN_PATH", r"<USER_HOME>\.juno\ow_admin_token.txt"))
    try:
        if p.exists():
            return p.read_text(encoding="utf-8").strip()
    except Exception:
        pass
    return os.getenv("OW_ADMIN_TOKEN", "")


def _ow_uppdatera_röst(voice: str) -> bool:
    """Uppdaterar OW config audio.tts.voice — samma värde OW skickar till proxyn vid varje TTS-anrop."""
    tok = _ow_token()
    if not tok:
        _felrapport("ow_uppdatera_röst", "OW-admin-token saknas")
        return False
    try:
        req = urllib.request.Request(
            "http://127.0.0.1:8080/api/v1/audio/config",
            headers={"Authorization": f"Bearer {tok}"})
        cfg = json.load(urllib.request.urlopen(req, timeout=15))
        cfg["tts"]["VOICE"] = voice
        data = json.dumps({"tts": cfg["tts"], "stt": cfg["stt"]}, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            "http://127.0.0.1:8080/api/v1/audio/config/update",
            data=data, method="POST",
            headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
        return urllib.request.urlopen(req, timeout=30).status == 200
    except Exception as exc:
        _felrapport("ow_uppdatera_röst", str(exc))
        return False

# ---------------------------------------------------------------- audit + felrapport (Regel 43)
def _audit(event: str, note: str = "", ok: bool = True) -> None:
    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        line = {"ts": ts, "event": event, "user": "rostproxy", "ok": ok, "note": note[:300]}
        with (LOGS_DIR / "rostproxy.log").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, ensure_ascii=False) + "\n")
    except Exception:
        pass

def _felrapport(kontext: str, msg: str) -> None:
    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        (LOGS_DIR / "felrapporter.log").open("a", encoding="utf-8").write(
            f"{ts} | ERROR | {kontext} | {msg}\n")
    except Exception:
        pass

# ---------------------------------------------------------------- hallucination-filter (P9, kravlistan §6)
_HALLUCINATION_REGEXES = [
    re.compile(r"\b(\w{2,})(?: \1){3,}\b"),   # "thank thank thank thank"
    re.compile(r"^(.)\1{5,}$"),               # "aaaaaa" / "......"
    re.compile(r"^[\W_]+$"),                  # bara skiljetecken/emoji
]

def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\såäöÅÄÖ]", " ", text.lower())).strip()

def _load_phrases() -> list[str]:
    """Läser fraslistan från logs/ (lokal, utökas vid mätning) — fallback till paketets kopia."""
    f = LOGS_DIR / "hallucination_phrases.txt"
    if not f.exists():
        f = Path(__file__).resolve().parent / "hallucination_phrases.txt"
    if not f.exists():
        return []
    return [l.strip().lower() for l in f.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.strip().startswith("#")]

def is_hallucination(text: str, phrases: list[str]) -> bool:
    n = _normalize(text)
    if len(n) <= 2:
        return True
    for rx in _HALLUCINATION_REGEXES:
        if rx.search(text):
            return True
    return any(p in n for p in phrases)

def filter_transcript(text: str, phrases: list[str]) -> str:
    # Skyddsregel (kravlistan §6.3): kassera bara om KORT yttrande (< 40 tecken) som matchar;
    # delfras i längre tal behålls med frasen intakt (äkta tal ska inte ätas).
    n = _normalize(text)
    if is_hallucination(text, phrases) and len(n) < 40:
        _audit("hallucination_filtrerad", note=repr(text[:120]))
        return ""
    return text

# ---------------------------------------------------------------- STT (kravlistan §5)
_whisper_model = None

def _get_whisper():
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel
        cfg = CONFIG["stt"]
        _whisper_model = WhisperModel(
            cfg["model"], device="cpu",
            compute_type=cfg["compute_type"], cpu_threads=cfg["cpu_threads"],
        )
    return _whisper_model

def _groq_api_key() -> str:
    """GROQ_API_KEY: miljövariabel först, sedan Hermes .env (%LOCALAPPDATA%\hermes\.env på Windows)."""
    key = os.getenv("GROQ_API_KEY", "").strip()
    if key:
        return key
    try:
        home = os.environ.get("LOCALAPPDATA", "")
        env_path = (Path(home) / "hermes" / ".env") if home else (Path.home() / ".hermes" / ".env")
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = line.strip()
                if line.startswith("GROQ_API_KEY="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return ""


def _groq_transcribe(wav_path: Path) -> str:
    """Groq Whisper (moln, ~0.3 s) via OpenAI-kompatibel endpoint."""
    key = _groq_api_key()
    if not key:
        raise RuntimeError("GROQ_API_KEY saknas — groq-STT kräver nyckeln")
    from openai import OpenAI
    client = OpenAI(api_key=key, base_url="https://api.groq.com/openai/v1")
    with open(wav_path, "rb") as fh:
        tr = client.audio.transcriptions.create(
            model=CONFIG["stt"]["groq_model"], file=fh, language=CONFIG["stt"]["language"],
        )
    return (tr.text or "").strip()


def _stt_motor() -> str:
    """Etikett för loggning: t.ex. 'groq:whisper-large-v3-turbo' eller 'whisper:base'."""
    cfg = CONFIG["stt"]
    if cfg.get("provider", "local") == "groq":
        return f"groq:{cfg['groq_model']}"
    return f"whisper:{cfg['model']}"


def transcribe(wav_path: Path) -> str:
    """STT: groq (moln, snabb) med lokal faster-whisper som fallback (P9: VAD + condition_on_previous_text=False)."""
    cfg = CONFIG["stt"]
    if cfg.get("provider", "local") == "groq":
        try:
            return _groq_transcribe(wav_path)
        except Exception as exc:
            _livefeed("WARN", f"Groq-STT misslyckades ({exc}) — faller tillbaka till lokal whisper")
    model = _get_whisper()
    segments, _info = model.transcribe(
        str(wav_path),
        language=cfg["language"],
        beam_size=cfg["beam_size"],
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=500),
        condition_on_previous_text=cfg["condition_on_previous_text"],
    )
    return "".join(s.text for s in segments).strip()

# ---------------------------------------------------------------- TTS (röstspec §4-valordning)
async def tts_edge(text: str, voice: str = "") -> bytes:
    import edge_tts
    voice = voice or CONFIG["tts"]["edge_voice_sv"]
    tts = edge_tts.Communicate(text, voice)
    buf = bytearray()
    async for chunk in tts.stream():
        if chunk["type"] == "audio":
            buf.extend(chunk["data"])
    return bytes(buf)

def tts_kokoro(text: str, voice: str = "") -> bytes:
    """Kokoro (endast engelska — röstspec §4: aldrig primär för svenska)."""
    from kokoro import KPipeline
    import numpy as np
    import soundfile as sf
    voice = voice or CONFIG["tts"]["kokoro_voice_en"]
    p = KPipeline(lang_code="a")
    audio = np.concatenate([a for _, _, a in p(text, voice=voice, speed=1.0)])
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as tmp:
        sf.write(tmp.name, audio, 24000)
        return tmp.read()

async def synthesize(text: str, voice: str = "") -> tuple[bytes, str]:
    """Valordning (§4): Edge sv-SE primär → Kokoro en fallback. Returnerar (audio, engine).
    Röst-id:n med prefixet `kokoro-` går direkt till Kokoro (röstväljarens tredje val)."""
    voice = voice or _läs_röstval() or CONFIG["tts"]["edge_voice_sv"]
    if voice.startswith("kokoro-"):
        try:
            audio = await asyncio.to_thread(tts_kokoro, text, voice[len("kokoro-"):])
            if audio:
                _audit("tts_kokoro", note=f"{len(audio)}B")
                return audio, "kokoro"
        except Exception as exc:
            _felrapport("tts_kokoro", str(exc))
        raise RuntimeError("Kokoro misslyckades")
    try:
        audio = await tts_edge(text, voice)
        if audio:
            _audit("tts_edge", note=f"{len(audio)}B")
            return audio, "edge"
    except Exception as exc:
        _felrapport("tts_edge", str(exc))
    try:
        audio = await asyncio.to_thread(tts_kokoro, text, voice)
        if audio:
            _audit("tts_kokoro", note=f"{len(audio)}B")
            return audio, "kokoro"
    except Exception as exc:
        _felrapport("tts_kokoro", str(exc))
    raise RuntimeError("Ingen TTS-engine tillgänglig (edge + kokoro misslyckades)")

# ---------------------------------------------------------------- FastAPI-app
def create_app():
    app = FastAPI(title="Juno Röstproxy", version="1.0.0")

    # CORS för Hermes Desktop-pluginet (origin localhost:8080 / file://-null).
    # Endast localhost-bindning (127.0.0.1:8765) — ingen fjärrexponering.
    from fastapi.middleware.cors import CORSMiddleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    @app.post("/v1/audio/speech")
    async def speech(request: Request):
        import time as _time
        t0 = _time.monotonic()
        try:
            payload = await request.json()
        except Exception:
            return JSONResponse({"error": "Invalid JSON"}, status_code=400)
        text = (payload.get("input") or "").strip()
        voice = payload.get("voice") or _läs_röstval() or CONFIG["tts"]["edge_voice_sv"]
        if not text:
            return JSONResponse({"error": "input krävs"}, status_code=400)
        try:
            audio, engine = await synthesize(text, voice)
        except Exception as exc:
            dur = _time.monotonic() - t0
            _livefeed("ERROR", f"TTS misslyckades ({dur:.1f}s): {exc}")
            raise
        dur = _time.monotonic() - t0
        _livefeed("INFO", f"TTS {dur:.1f}s {len(audio)/1024:.1f}KB (motor={engine}, röst={voice})")
        return Response(content=audio, media_type="audio/mpeg",
                        headers={"X-TTS-Engine": engine})

    @app.post("/v1/audio/transcriptions")
    async def transcriptions(request: Request):
        import time as _time
        t0 = _time.monotonic()
        form = await request.form()
        file = form.get("file")
        if file is None:
            return JSONResponse({"error": "file krävs"}, status_code=400)
        data = await file.read()
        suffix = Path(file.filename or "audio.wav").suffix or ".wav"
        # Windows: delete=False (delete=True raderar vid close → tom fil för transkriberingen)
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(data)
                tmp.flush()
                tmp_path = Path(tmp.name)
            try:
                raw = await asyncio.to_thread(transcribe, tmp_path)
            except Exception as exc:
                _felrapport("stt_transcribe", str(exc))
                _livefeed("ERROR", f"STT misslyckades: {exc}")
                return JSONResponse({"text": ""})
        finally:
            if tmp_path is not None and tmp_path.exists():
                try:
                    tmp_path.unlink()
                except Exception:
                    pass
        dur = _time.monotonic() - t0
        text = filter_transcript(raw, _load_phrases())
        _audit("stt", note=f"{len(text)} tecken")
        if not text and raw:
            _livefeed("WARN", f"STT {dur:.1f}s filtrerad som hallucination ({len(raw)} tecken råtext)")
        else:
            _livefeed("INFO", f"STT {dur:.1f}s {len(text)} tecken (motor={_stt_motor()})")
        return JSONResponse({"text": text})

    @app.get("/v1/voices")
    async def voices():
        return {"voices": VOICES, "current": _läs_röstval() or CONFIG["tts"]["edge_voice_sv"]}

    @app.get("/v1/voice")
    async def voice_get():
        return {"voice": _läs_röstval() or CONFIG["tts"]["edge_voice_sv"]}

    @app.put("/v1/voice")
    async def voice_put(request: Request):
        try:
            payload = await request.json()
        except Exception:
            return JSONResponse({"error": "Invalid JSON"}, status_code=400)
        voice = (payload.get("voice") or "").strip()
        if voice not in {v["id"] for v in VOICES}:
            return JSONResponse(
                {"error": f"Okänd röst. Välj bland: {', '.join(v['id'] for v in VOICES)}"},
                status_code=400)
        ok_ow = _ow_uppdatera_röst(voice)
        _spara_röstval(voice)
        _audit("röst_sätt", note=f"{voice} (ow={ok_ow})", ok=ok_ow)
        _livefeed("INFO", f"Röst bytt till {voice} (OW-config {'uppdaterad' if ok_ow else 'EJ uppdaterad'})")
        return {"voice": voice, "ow_uppdaterad": ok_ow, "gäller_nu": True}

    @app.get("/measure/voice")
    async def measure_voice():
        """Mät röstkedjan (STT -> LLM -> TTS) i 3 rundor, median per del.

        Skrivskyddad, inga hemligheter. Fixturen (svensk talasset, ~3,7 s)
        ligger lokalt under juno_core/services/assets/ och transkriberas via
        Groq; LLM-första-token mäts via Groq (stream, CONFIG["llm"]["groq_model"]);
        TTS-första-ljud mäts via Edge sv-SE. Totalen = tal -> hörbart svar.
        """
        fixture = PROJECT_ROOT / "juno_core" / "services" / "assets" / "measure_fixture.wav"
        if not fixture.exists():
            return JSONResponse(
                {"error": "measure_fixture.wav saknas under juno_core/services/assets/"},
                status_code=503,
            )
        key = _groq_api_key()
        if not key:
            return JSONResponse({"error": "GROQ_API_KEY saknas (hermes/.env)"}, status_code=503)
        from openai import OpenAI
        client = OpenAI(api_key=key, base_url="https://api.groq.com/openai/v1")

        rounds: list[dict] = []
        transcript = ""
        for _r in range(3):
            leg: dict = {}
            # --- STT: Groq Whisper på fast svensk fixture ---
            t0 = time.perf_counter()
            with open(fixture, "rb") as fh:
                tr = client.audio.transcriptions.create(
                    model=CONFIG["stt"]["groq_model"], file=fh, language=CONFIG["stt"]["language"],
                )
            transcript = (tr.text or "").strip()
            leg["stt_s"] = round(time.perf_counter() - t0, 3)
            # --- LLM: första token via Groq llama (stream) ---
            t0 = time.perf_counter()
            stream = client.chat.completions.create(
                model=CONFIG["llm"]["groq_model"],
                messages=[{"role": "user", "content": "Svara med ett enda ord: hej."}],
                max_tokens=16,
                stream=True,
            )
            first_token_s = None
            for _ch in stream:
                first_token_s = time.perf_counter() - t0
                break
            leg["llm_s"] = round(first_token_s, 3) if first_token_s is not None else None
            # --- TTS: första ljudchunk via Edge sv-SE (hörbart svar) ---
            import edge_tts
            t0 = time.perf_counter()
            comm = edge_tts.Communicate(
                "Hej, detta är ett test av röstsvar.", CONFIG["tts"]["edge_voice_sv"],
            )
            first_audio_s = None
            async for chunk in comm.stream():
                if chunk["type"] == "audio":
                    first_audio_s = time.perf_counter() - t0
                    break
            leg["tts_s"] = round(first_audio_s, 3) if first_audio_s is not None else None
            rounds.append(leg)

        def _med(key: str) -> float:
            vals = [r[key] for r in rounds if r.get(key) is not None]
            return round(statistics.median(vals), 3) if vals else None

        stt_m, llm_m, tts_m = _med("stt_s"), _med("llm_s"), _med("tts_s")
        total = round(sum(v for v in (stt_m, llm_m, tts_m) if v), 3)
        result = {
            "status": "ok",
            "rundor": len(rounds),
            "fixture": "piper sv_SE-nst-medium, ~3,7 s svenska",
            "stt": {"motor": _stt_motor(), "median_s": stt_m, "rundor_s": [r["stt_s"] for r in rounds]},
            "llm": {"motor": f"groq:{CONFIG['llm']['groq_model']}", "median_s": llm_m},
            "tts": {"motor": f"edge:{CONFIG['tts']['edge_voice_sv']}", "median_s": tts_m},
            "total_median_s": total,
            "transkript": transcript,
        }
        _audit("measure", note=f"stt={stt_m}s llm={llm_m}s tts={tts_m}s total={total}s")
        _livefeed("INFO", f"Mätning: total {total}s (STT {stt_m} + LLM {llm_m} + TTS {tts_m})")
        return result

    @app.get("/health")
    async def health():
        stt_ok = False
        try:
            if CONFIG["stt"].get("provider", "local") == "groq":
                stt_ok = bool(_groq_api_key())
            else:
                _get_whisper()
                stt_ok = True
        except Exception:
            pass
        return {"status": "ok", "vad": True, "stt_provider": CONFIG["stt"].get("provider", "local"),
                "stt_model": _stt_motor(),
                "stt_ready": stt_ok, "tts_primary": "edge-sv-SE",
                "voice": _läs_röstval() or CONFIG["tts"]["edge_voice_sv"]}

    return app

# ---------------------------------------------------------------- main
def main() -> None:
    import uvicorn
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    _audit("start", note=f"port {PORT}")
    _livefeed("INFO", f"Röstproxy start (port {PORT})")
    app = create_app()
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")

if __name__ == "__main__":
    main()
