"""
Audio Data Processor

Minimal local audio-to-text using faster-whisper.

Runs on Windows and Raspberry Pi with the same code path:
    pip install faster-whisper

The main public helper is ``audio_to_text`` which takes a websocket-style
payload like ``{"filename": ..., "mime_type": ..., "data": <base64>}``
and returns the transcribed text.
"""

import base64
import os
import tempfile
import wave
from pathlib import Path
from typing import Any, Dict, Optional

from faster_whisper import WhisperModel
from piper import PiperVoice


# Env-tunable so the same code runs on Windows dev boxes and Raspberry Pi.
# On Pi, prefer "tiny" + "int8" for usable latency.
_DEFAULT_MODEL = os.getenv("WHISPER_MODEL", "base")
_DEFAULT_DEVICE = os.getenv("WHISPER_DEVICE", "cpu")
_DEFAULT_COMPUTE = os.getenv("WHISPER_COMPUTE", "int8")

_MODEL: Optional[WhisperModel] = None


def _get_model() -> WhisperModel:
    """Lazy-load and cache the whisper model."""
    global _MODEL
    if _MODEL is None:
        _MODEL = WhisperModel(
            _DEFAULT_MODEL,
            device=_DEFAULT_DEVICE,
            compute_type=_DEFAULT_COMPUTE,
        )
    return _MODEL


def audio_bytes_to_text(raw: bytes) -> str:
    """
    Transcribe raw audio bytes to text using faster-whisper.

    Args:
        raw: Raw audio bytes (e.g. decoded from base64).

    Returns:
        Transcribed text.
    """
    model = _get_model()
    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
        tmp.write(raw)
        tmp_path = tmp.name
    try:
        segments, _info = model.transcribe(tmp_path, beam_size=1)
        return " ".join(seg.text for seg in segments).strip()
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def audio_to_text(audio: Dict[str, Any]) -> str:
    """
    Transcribe a websocket audio payload to text.

    Args:
        audio: Dict with ``filename`` (optional), ``mime_type`` (optional)
            and base64 ``data`` keys.

    Returns:
        Transcribed text.
    """
    if not isinstance(audio, dict):
        raise ValueError("Audio payload must be a dict with 'data'.")

    data = audio.get("data")
    if not data:
        raise ValueError("Audio payload is missing 'data' (base64 string).")

    # Strip an optional ``data:<mime>;base64,`` prefix.
    if isinstance(data, str) and data.startswith("data:"):
        try:
            _, data = data.split(",", 1)
        except ValueError as exc:
            raise ValueError("Malformed data URI in audio payload.") from exc

    try:
        raw = base64.b64decode(data, validate=False)
    except Exception as exc:
        raise ValueError(f"Audio payload is not valid base64: {exc}") from exc

    if not raw:
        raise ValueError("Audio payload decoded to zero bytes.")

    return audio_bytes_to_text(raw)


# Override by setting PIPER_MODEL=/abs/path/to/<voice>.onnx before running.
_DEFAULT_PIPER_MODEL = os.getenv("PIPER_MODEL", "en_US-ryan-high.onnx")

_PIPER_VOICE: Optional[PiperVoice] = None


def _get_piper_voice() -> PiperVoice:
    """Lazy-load and cache the piper voice."""
    global _PIPER_VOICE
    if _PIPER_VOICE is None:
        model_path = Path(_DEFAULT_PIPER_MODEL)
        # piper needs BOTH <voice>.onnx and <voice>.onnx.json side-by-side.
        if not model_path.exists():
            raise FileNotFoundError(
                f"PIPER_MODEL not found: {model_path}. "
                "Download the .onnx and the matching .onnx.json and put "
                "them in the same folder, then set PIPER_MODEL to the .onnx."
            )
        json_path = model_path.with_suffix(".onnx.json")
        if not json_path.exists():
            raise FileNotFoundError(
                f"Missing sidecar config for Piper voice: {json_path}. "
                "PiperVoice.load needs the .onnx.json next to the .onnx."
            )
        _PIPER_VOICE = PiperVoice.load(str(model_path))
        # Some Piper builds leave config.sample_rate as None until first use.
        if not getattr(_PIPER_VOICE.config, "sample_rate", None):
            _PIPER_VOICE.config.sample_rate = 22050
    return _PIPER_VOICE


def _synthesize_wav(text: str) -> bytes:
    """Synthesize text once and return raw WAV bytes (internal)."""
    if not text or not text.strip():
        raise ValueError("text must be a non-empty string.")

    voice = _get_piper_voice()
    sample_rate = getattr(voice.config, "sample_rate", None) or 22050

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
    tmp.close()
    out_path = tmp.name
    try:
        with wave.open(out_path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)         # 16-bit
            w.setframerate(sample_rate)
            written = 0
            for chunk in voice.synthesize(text):
                if chunk.audio_int16_bytes:
                    w.writeframes(chunk.audio_int16_bytes)
                    written += len(chunk.audio_int16_bytes)
        if written == 0:
            raise RuntimeError(
                "Piper produced 0 audio bytes. Check that the .onnx.json "
                "sidecar is present and that the text is not empty."
            )
        return Path(out_path).read_bytes()
    finally:
        Path(out_path).unlink(missing_ok=True)


def _wav_bytes_to_payload(raw: bytes) -> Dict[str, Any]:
    """Wrap raw WAV bytes into the websocket-style base64 payload."""
    return {
        "filename": "speech.wav",
        "mime_type": "audio/wav",
        "data": base64.b64encode(raw).decode("ascii"),
    }


def text_to_audio_bytes(text: str) -> bytes:
    """Synthesize text to raw WAV bytes using piper1-gpl (in-process)."""
    return _synthesize_wav(text)


def text_to_audio(text: str) -> Dict[str, Any]:
    """Synthesize text and return a websocket-style base64 payload."""
    return _wav_bytes_to_payload(_synthesize_wav(text))


__all__ = [
    "audio_to_text",
    "audio_bytes_to_text",
    "text_to_audio",
    "text_to_audio_bytes",
]


if __name__ == "__main__":
    """Quick local smoke test using test.mp3 sitting next to this file."""
    test_file = Path(__file__).parent / "test.mp3"
    if not test_file.exists():
        raise SystemExit(f"test.mp3 not found at {test_file}")

    raw_bytes = test_file.read_bytes()
    print(f"[1] audio_bytes_to_text on {test_file.name} ({len(raw_bytes)} bytes)...")
    text_from_bytes = audio_bytes_to_text(raw_bytes)
    print(f"    -> {text_from_bytes!r}")

    print(f"[2] audio_to_text via base64 payload...")
    payload = {
        "filename": test_file.name,
        "mime_type": "audio/mpeg",
        "data": base64.b64encode(raw_bytes).decode("ascii"),
    }
    text_from_payload = audio_to_text(payload)
    print(f"    -> {text_from_payload!r}")

    assert text_from_bytes == text_from_payload, "Mismatch between the two paths!"
    print("OK: both paths produced identical transcription.")

    print(f"[3] text_to_audio_bytes / text_to_audio on a sample sentence...")
    sample = "Hello from Piper text to speech, running on this machine."
    try:
        wav_bytes = text_to_audio_bytes(sample)
    except FileNotFoundError as exc:
        print(f"    -> skipped (PIPER_MODEL not set / voice not found): {exc}")
    else:
        print(f"    -> produced {len(wav_bytes)} WAV bytes")
        tts_payload = text_to_audio(sample)
        # Save to disk so you can listen to it.
        out_path = Path(__file__).parent / "test_tts_output.wav"
        out_path.write_bytes(wav_bytes)
        print(f"    -> saved to {out_path}")
        print("OK: TTS path produced a valid payload.")