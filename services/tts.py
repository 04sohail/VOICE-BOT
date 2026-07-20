import os
import tempfile
import asyncio
import json
import io
import numpy as np
import soundfile as sf

# Load VoXtream natively if explicitly enabled by the user
generator = None
USE_VOXTREAM = os.getenv("USE_VOXTREAM", "False").lower() in ("true", "1", "yes")

if USE_VOXTREAM:
    try:
        print(
            "Initializing VoXtream model natively (Warning: Requires GPU for low latency)..."
        )
        from voxtream.generator import SpeechGenerator, SpeechGeneratorConfig

        config_path = "configs/generator.json"
        with open(config_path) as f:
            config = SpeechGeneratorConfig(**json.load(f))

        spk_rate_config_path = "configs/speaking_rate.json"
        with open(spk_rate_config_path) as f:
            spk_rate_config = json.load(f)

        generator = SpeechGenerator(config, spk_rate_config)
        print("VoXtream model successfully loaded!")
    except Exception as e:
        print(f"Could not load VoXtream model natively: {e}")


async def generate_speech(text: str) -> bytes:
    """
    Connects to edge-tts for Text-To-Speech generation by default.
    If USE_VOXTREAM is true, it uses the local VoXtream model instead.
    """
    if generator is not None:
        try:
            loop = asyncio.get_event_loop()

            def do_generate():
                from pathlib import Path

                prompt_path = Path("assets/audio/prompt.wav")

                # generate_stream yields chunks of float32 numpy arrays
                audio_frames = []
                for frame, _ in generator.generate_stream(prompt_path, text):
                    audio_frames.append(frame)

                final_audio = np.concatenate(audio_frames)

                # Convert the raw float32 PCM into a WAV file buffer
                buffer = io.BytesIO()
                sf.write(buffer, final_audio, 24000, format="WAV", subtype="PCM_16")
                return buffer.getvalue()

            return await loop.run_in_executor(None, do_generate)
        except Exception as e:
            print(f"VoXtream generation error: {e}. Falling back to Edge-TTS...")

    # Fallback to Edge-TTS
    try:
        import edge_tts

        communicate = edge_tts.Communicate(text, "en-US-ChristopherNeural", rate="+10%")

        audio_data = bytearray()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_data.extend(chunk["data"])

        return bytes(audio_data)
    except ImportError:
        print("Edge-TTS not installed. No audio generated.")
        return b""
    except Exception as e:
        print(f"Edge-TTS Error: {e}")
        return b""
