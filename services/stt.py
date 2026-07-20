import os
import tempfile
import whisper
import asyncio

# Load the model once globally for fast inference
try:
    print("Loading local Whisper model (small.en) for higher accuracy...")
    # 'small.en' is significantly more accurate than 'base.en' while remaining fast
    model = whisper.load_model("small.en")
    print("Whisper model loaded.")
except Exception as e:
    print(f"Error loading Whisper model: {e}")
    model = None


async def transcribe_audio(audio_bytes: bytes) -> str:
    """
    Uses a local Whisper model to transcribe audio.
    """
    if model is None:
        return "Whisper model not initialized."

    try:


        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_audio:
            temp_audio.write(audio_bytes)
            temp_filename = temp_audio.name
            print(f"[STT] Saved {len(audio_bytes)} bytes to {temp_filename}", flush=True)

        # Run transcription in a separate thread so it doesn't block the async loop
        loop = asyncio.get_event_loop()

        # Local whisper's transcribe method takes a file path
        def do_transcribe():
            return model.transcribe(
                temp_filename,
                language="en",
                fp16=False,
                no_speech_threshold=0.6,
                condition_on_previous_text=False,
            )

        print(f"[STT] Running transcription...", flush=True)
        result = await loop.run_in_executor(None, do_transcribe)
        print(f"[STT] Raw result: {result}", flush=True)

        os.remove(temp_filename)
        text = result.get("text", "").strip()

        if len(text) < 2:
            return ""

        return text
    except Exception as e:
        print(f"STT (Local Whisper) Error: {e}", flush=True)
        return ""
