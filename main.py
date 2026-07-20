import os
import json
import asyncio
import io
import wave
import numpy as np
from fastapi import FastAPI, Request, Depends, HTTPException, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import secrets
from dotenv import load_dotenv

load_dotenv()

from services.stt import transcribe_audio
from services.llm import generate_response
from services.tts import generate_speech

from livekit import rtc, api

app = FastAPI(title="AI Voice Agent - LiveKit")

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

security = HTTPBasic()

def get_current_username(credentials: HTTPBasicCredentials = Depends(security)):
    expected_username = os.getenv("AUTH_USERNAME", "admin")
    expected_password = os.getenv("AUTH_PASSWORD", "password")

    correct_username = secrets.compare_digest(credentials.username, expected_username)
    correct_password = secrets.compare_digest(credentials.password, expected_password)
    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

@app.get("/", response_class=HTMLResponse)
async def index(request: Request, username: str = Depends(get_current_username)):
    return templates.TemplateResponse(request=request, name="index.html")

@app.get("/api/token")
async def get_token():
    """Generates a LiveKit connection token for the frontend."""
    api_key = os.getenv("LIVEKIT_API_KEY", "devkey")
    api_secret = os.getenv("LIVEKIT_API_SECRET", "secret")
    grant = api.VideoGrants(room_join=True, room="voice_room")
    token = api.AccessToken(api_key, api_secret).with_grants(grant).with_identity("user").with_name("User").to_jwt()
    public_url = os.getenv("LIVEKIT_PUBLIC_URL", "ws://localhost:7880")
    return {"token": token, "url": public_url}


# --- LIVEKIT AGENT LOGIC ---

chat_history = [
    {
        "role": "system",
        "content": "You are a highly conversational AI voice assistant. Keep answers brief and natural.",
    }
]

async def send_ui_message(room: rtc.Room, data: dict):
    try:
        await room.local_participant.publish_data(
            json.dumps(data).encode('utf-8'),
            reliable=True
        )
    except Exception as e:
        print("Failed to send UI data:", e)

async def process_user_audio(audio_bytes, audio_source, room):
    import time
    try:
        t_stt_start = time.time()
        user_text = await transcribe_audio(audio_bytes)
        t_stt_end = time.time()
        
        print(f"User said: {user_text}")
        print(f"⏱️ [TIMING] STT (Whisper) took {t_stt_end - t_stt_start:.3f}s", flush=True)
        
        if not user_text or not user_text.strip():
            return
            
        print("Sending UI transcript message...", flush=True)
        await send_ui_message(room, {"type": "transcript", "role": "user", "content": user_text})
        chat_history.append({"role": "user", "content": user_text})

        print("Sending UI thinking message...", flush=True)
        await send_ui_message(room, {"type": "status", "content": "thinking"})

        print("Generating response...", flush=True)
        # Generate response
        response_text = ""
        sentence_buffer = ""
        
        t_llm_start = time.time()
        first_token = True
        
        async for chunk in generate_response(chat_history):
            if first_token:
                print(f"⏱️ [TIMING] LLM Time to First Token (TTFT) took {time.time() - t_llm_start:.3f}s", flush=True)
                first_token = False
                
            response_text += chunk
            sentence_buffer += chunk

            clean_chunk = chunk.replace("[END_CALL]", "")
            if clean_chunk:
                await send_ui_message(room, {"type": "transcript_chunk", "role": "assistant", "content": clean_chunk})

            if any(p in sentence_buffer for p in [". ", "? ", "! ", "\n"]):
                for p in [". ", "? ", "! ", "\n"]:
                    if p in sentence_buffer:
                        parts = sentence_buffer.split(p, 1)
                        sentence = parts[0] + p.strip()
                        sentence_buffer = parts[1]

                        sentence_clean = sentence.replace("[END_CALL]", "").strip()
                        if sentence_clean:
                            t_tts_start = time.time()
                            wav_bytes = await generate_speech(sentence_clean)
                            t_tts_end = time.time()
                            print(f"⏱️ [TIMING] TTS generated sentence in {t_tts_end - t_tts_start:.3f}s: '{sentence_clean}'", flush=True)
                            
                            if wav_bytes:
                                await play_wav_to_livekit(wav_bytes, audio_source)
                        break

        # Remaining buffer
        sentence_clean = sentence_buffer.replace("[END_CALL]", "").strip()
        if sentence_clean:
            t_tts_start = time.time()
            wav_bytes = await generate_speech(sentence_clean)
            t_tts_end = time.time()
            print(f"⏱️ [TIMING] TTS generated sentence in {t_tts_end - t_tts_start:.3f}s: '{sentence_clean}'", flush=True)
            
            if wav_bytes:
                await play_wav_to_livekit(wav_bytes, audio_source)
                
        print(f"⏱️ [TIMING] Total LLM Response generation took {time.time() - t_llm_start:.3f}s", flush=True)

        chat_history.append({"role": "assistant", "content": response_text.replace("[END_CALL]", "")})
        
        await send_ui_message(room, {
            "type": "transcript_complete", 
            "role": "assistant", 
            "content": response_text.replace("[END_CALL]", "")
        })
        
        if "[END_CALL]" in response_text:
            print("AI ended the call.")
            await send_ui_message(room, {"type": "end_call"})
            
    except Exception as e:
        print(f"Error in turn: {e}")

async def play_wav_to_livekit(audio_bytes, audio_source):
    import subprocess
    
    # Use ffmpeg to decode MP3/WAV into 16-bit 48kHz mono PCM
    process = await asyncio.create_subprocess_exec(
        'ffmpeg', '-i', 'pipe:0', '-f', 's16le', '-ar', '48000', '-ac', '1', 'pipe:1',
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
    )
    pcm_bytes, _ = await process.communicate(input=audio_bytes)
    
    # Push 10ms frames (480 samples = 960 bytes for 16-bit)
    frame_size = 960
    for i in range(0, len(pcm_bytes), frame_size):
        chunk = pcm_bytes[i:i+frame_size]
        if len(chunk) < frame_size:
            chunk += b'\x00' * (frame_size - len(chunk))
        
        frame = rtc.AudioFrame(
            data=chunk,
            sample_rate=48000,
            num_channels=1,
            samples_per_channel=480
        )
        await audio_source.capture_frame(frame)


async def handle_incoming_audio(audio_stream: rtc.AudioStream, audio_source: rtc.AudioSource, room: rtc.Room):
    print("Started listening to user audio stream!")
    frames = []
    is_speaking = False
    silence_frames = 0
    consecutive_speech_frames = 0
    
    # 48000Hz, 16-bit mono -> 10ms frame is 960 bytes (480 samples)
    logged_format = False
    async for event in audio_stream:
        if not logged_format:
            print(f"[AUDIO] Stream properties: rate={event.frame.sample_rate}, channels={event.frame.num_channels}, samples={event.frame.samples_per_channel}", flush=True)
            logged_format = True
        
        data = np.frombuffer(event.frame.data, dtype=np.int16)
        # Calculate RMS
        rms = np.sqrt(np.mean(data.astype(np.float32)**2))
        
        if rms > 150: # Adjust threshold as needed
            consecutive_speech_frames += 1
            if consecutive_speech_frames > 5:
                if not is_speaking:
                    is_speaking = True
                    print("🎤 User started speaking...")
                silence_frames = 0
            frames.append(event.frame.data)
        else:
            consecutive_speech_frames = 0
            if is_speaking:
                frames.append(event.frame.data)
                silence_frames += 1
                # 10ms per frame. 150 frames = 1.5 seconds of silence
                if silence_frames > 150:
                    is_speaking = False
                    print("🛑 User stopped speaking. Processing...")
                    
                    # Convert raw PCM frames to WAV bytes for Whisper
                    pcm_data = b"".join(frames)
                    wav_io = io.BytesIO()
                    with wave.open(wav_io, 'wb') as wf:
                        wf.setnchannels(1)
                        wf.setsampwidth(2)
                        wf.setframerate(48000)
                        wf.writeframes(pcm_data)
                    
                    asyncio.create_task(process_user_audio(wav_io.getvalue(), audio_source, room))
                    frames = []
        
        # Don't buffer forever if not speaking
        if not is_speaking and len(frames) > 50:
            frames.pop(0)

async def livekit_agent_worker():
    api_key = os.getenv("LIVEKIT_API_KEY", "devkey")
    api_secret = os.getenv("LIVEKIT_API_SECRET", "secret")
    
    # Connect to the docker service name if in docker, otherwise fallback to env
    livekit_url = os.getenv("LIVEKIT_URL", "ws://livekit-server:7880")
    
    # Wait for LiveKit server to start up
    await asyncio.sleep(5)
    
    room = rtc.Room()
    
    audio_source = rtc.AudioSource(48000, 1)
    track = rtc.LocalAudioTrack.create_audio_track("agent-mic", audio_source)
    options = rtc.TrackPublishOptions()
    options.source = rtc.TrackSource.SOURCE_MICROPHONE
    
    @room.on("track_subscribed")
    def on_track_subscribed(track: rtc.Track, publication: rtc.RemoteTrackPublication, participant: rtc.RemoteParticipant):
        if track.kind == rtc.TrackKind.KIND_AUDIO:
            audio_stream = rtc.AudioStream(track)
            asyncio.create_task(handle_incoming_audio(audio_stream, audio_source, room))

    # Connect to room
    grant = api.VideoGrants(
        room_join=True,
        room="voice_room",
    )
    token = api.AccessToken(api_key, api_secret).with_grants(grant).with_identity("agent").with_name("Agent").to_jwt()
    try:
        await room.connect(livekit_url, token)
        print("🤖 LiveKit Agent Connected to Room!", flush=True)
        await room.local_participant.publish_track(track, options)
    except Exception as e:
        print("Failed to connect agent:", e, flush=True)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(livekit_agent_worker())
