import os
import json
import asyncio
from fastapi import (
    FastAPI,
    WebSocket,
    Request,
    WebSocketDisconnect,
    Depends,
    HTTPException,
    status,
)
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import secrets
from dotenv import load_dotenv

from services.stt import transcribe_audio
from services.llm import generate_response
from services.tts import generate_speech

load_dotenv()

app = FastAPI(
    title="AI Voice Agent",
    description="Low latency Voice Agent with OpenRouter, Whisper, and VoxStream",
)

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


async def handle_user_turn(
    websocket: WebSocket, audio_bytes: bytes, chat_history: list
):
    try:
        # 1. Speech-to-Text (Whisper)
        user_text = await transcribe_audio(audio_bytes)
        print(f"User said: {user_text}")

        if not user_text or not user_text.strip():
            return

        chat_history.append({"role": "user", "content": user_text})

        # Send transcribed text back to frontend
        await websocket.send_text(
            json.dumps({"type": "transcript", "role": "user", "content": user_text})
        )

        # 2. LLM (OpenRouter)
        response_text = ""
        sentence_buffer = ""

        await websocket.send_text(json.dumps({"type": "status", "content": "thinking"}))
        await websocket.send_text(json.dumps({"type": "audio_start"}))

        async for chunk in generate_response(chat_history):
            response_text += chunk
            sentence_buffer += chunk

            await websocket.send_text(
                json.dumps(
                    {"type": "transcript_chunk", "role": "assistant", "content": chunk}
                )
            )

            # Split into sentences to stream TTS audio quickly
            if any(p in sentence_buffer for p in [". ", "? ", "! ", "\n"]):
                for p in [". ", "? ", "! ", "\n"]:
                    if p in sentence_buffer:
                        parts = sentence_buffer.split(p, 1)
                        sentence = parts[0] + p.strip()
                        sentence_buffer = parts[1]

                        if sentence.strip():
                            audio_chunk = await generate_speech(sentence.strip())
                            if audio_chunk:
                                await websocket.send_bytes(audio_chunk)
                        break

        # Send any remaining text
        if sentence_buffer.strip():
            audio_chunk = await generate_speech(sentence_buffer.strip())
            if audio_chunk:
                await websocket.send_bytes(audio_chunk)

        chat_history.append({"role": "assistant", "content": response_text})

        await websocket.send_text(
            json.dumps(
                {
                    "type": "transcript_complete",
                    "role": "assistant",
                    "content": response_text,
                }
            )
        )

        await websocket.send_text(json.dumps({"type": "audio_end"}))
    except asyncio.CancelledError:
        print("AI generation interrupted by user!")
    except Exception as e:
        print(f"Error in turn: {e}")


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    print("WebSocket connected")

    chat_history = [
        {
            "role": "system",
            "content": "You are a highly conversational AI voice assistant. Keep answers brief and natural.",
        }
    ]
    current_task = None

    try:
        while True:
            message = await websocket.receive()

            if "text" in message:
                try:
                    data = json.loads(message["text"])
                    if data.get("type") == "interrupt":
                        if current_task and not current_task.done():
                            current_task.cancel()
                except:
                    pass

            if "bytes" in message:
                audio_bytes = message["bytes"]

                # If user speaks while AI is talking, interrupt it
                if current_task and not current_task.done():
                    current_task.cancel()

                current_task = asyncio.create_task(
                    handle_user_turn(websocket, audio_bytes, chat_history)
                )

    except WebSocketDisconnect:
        print("WebSocket disconnected")
    except Exception as e:
        print(f"Error in websocket loop: {e}")
