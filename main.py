import os
import json
import asyncio
from fastapi import FastAPI, Request, Depends, HTTPException, status, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import secrets
from dotenv import load_dotenv

from google import genai
from google.genai import types

load_dotenv()
import json

DB_PATH = "database.json"

def load_db():
    if not os.path.exists(DB_PATH):
        # Default calendar
        default_db = {
            "calendar": {
                "Monday": ["10:00 AM", "02:00 PM"],
                "Tuesday": ["11:00 AM", "01:00 PM"],
                "Wednesday": ["09:30 AM", "03:00 PM"],
                "Thursday": ["08:00 AM", "12:00 PM", "04:00 PM"],
                "Friday": ["10:00 AM", "02:00 PM"]
            },
            "appointments": []
        }
        with open(DB_PATH, "w") as f:
            json.dump(default_db, f, indent=2)
        return default_db
    with open(DB_PATH, "r") as f:
        return json.load(f)

def save_db(data):
    with open(DB_PATH, "w") as f:
        json.dump(data, f, indent=2)

def check_availability(day: str) -> str:
    db = load_db()
    slots = db.get("calendar", {}).get(day.capitalize(), [])
    if slots:
        return f"Available slots on {day}: {', '.join(slots)}"
    return f"No available slots on {day}."

def book_appointment(day: str, time: str, name: str) -> str:
    db = load_db()
    slots = db.get("calendar", {}).get(day.capitalize(), [])
    if time not in slots:
        return f"Sorry, {time} is not available on {day}. Note: You must use the exact format from check_availability, e.g. '10:00 AM'"
    
    slots.remove(time)
    db["calendar"][day.capitalize()] = slots
    db.setdefault("appointments", []).append({"day": day, "time": time, "name": name})
    save_db(db)
    
    return f"Appointment successfully booked for {name} on {day} at {time}."

def cancel_appointment(name: str, day: str, time: str) -> str:
    db = load_db()
    appointments = db.get("appointments", [])
    for apt in appointments:
        if apt.get("name").lower() == name.lower() and apt.get("day").lower() == day.lower() and apt.get("time") == time:
            appointments.remove(apt)
            db["appointments"] = appointments
            # Add back to available slots
            db.setdefault("calendar", {}).setdefault(day.capitalize(), []).append(time)
            save_db(db)
            return f"Appointment cancelled for {name} on {day} at {time}."
    return f"No appointment found for {name} on {day} at {time}."

def reschedule_appointment(name: str, old_day: str, old_time: str, new_day: str, new_time: str) -> str:
    db = load_db()
    new_slots = db.get("calendar", {}).get(new_day.capitalize(), [])
    if new_time not in new_slots:
        return f"Sorry, the new time {new_time} is not available on {new_day}."
        
    cancel_msg = cancel_appointment(name, old_day, old_time)
    if "No appointment found" in cancel_msg:
        return cancel_msg
        
    book_msg = book_appointment(new_day, new_time, name)
    return f"Successfully rescheduled. New appointment details: {new_day} at {new_time}."

app = FastAPI(title="AI Voice Agent - Gemini Live API")

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

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    import time
    print("Incoming websocket connection request...", flush=True)
    await websocket.accept()
    print("Websocket accepted.", flush=True)
    
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("GEMINI_API_KEY is not set.", flush=True)
        await websocket.close()
        return

    client = genai.Client(api_key=api_key)
    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-native-audio-latest")
    
    config = {
        "response_modalities": ["AUDIO"],
        "system_instruction": {"parts": [{"text": "You are a friendly, professional AI dental receptionist for Dr. Smith's Clinic. You MUST NOT narrate your actions, and you MUST NOT output inner thoughts or text inside asterisks. Never say 'Re-establishing persona'. Keep answers strictly under 2 sentences and sound entirely natural and conversational. If the user asks an irrelevant or off-topic question, politely decline by saying something like 'I cannot provide answers related to [topic], but I can help you schedule an appointment with Dr. Smith or answer questions about our dental services.'"}]},
        "tools": [{"function_declarations": [
            {
                "name": "check_availability",
                "description": "Returns available time slots for a specific day.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "day": {"type": "STRING", "description": "The day of the week, e.g. Monday, Tuesday"}
                    },
                    "required": ["day"]
                }
            },
            {
                "name": "book_appointment",
                "description": "Books an appointment for a patient at a specific day and time.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "day": {"type": "STRING", "description": "The day of the week, e.g. Monday"},
                        "time": {"type": "STRING", "description": "The time of the appointment, EXACTLY matching the format from check_availability, e.g. 10:00 AM"},
                        "name": {"type": "STRING", "description": "The full name of the patient"}
                    },
                    "required": ["day", "time", "name"]
                }
            },
            {
                "name": "cancel_appointment",
                "description": "Cancels an existing appointment for a patient.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "name": {"type": "STRING", "description": "The full name of the patient"},
                        "day": {"type": "STRING", "description": "The day of the week, e.g. Monday"},
                        "time": {"type": "STRING", "description": "The time of the appointment, e.g. 10:00 AM"}
                    },
                    "required": ["name", "day", "time"]
                }
            },
            {
                "name": "reschedule_appointment",
                "description": "Reschedules an appointment from an old time to a new time.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "name": {"type": "STRING", "description": "The full name of the patient"},
                        "old_day": {"type": "STRING", "description": "The original day of the appointment"},
                        "old_time": {"type": "STRING", "description": "The original time of the appointment"},
                        "new_day": {"type": "STRING", "description": "The new day of the appointment"},
                        "new_time": {"type": "STRING", "description": "The new time of the appointment"}
                    },
                    "required": ["name", "old_day", "old_time", "new_day", "new_time"]
                }
            }
        ]}],
        "speech_config": {
            "voice_config": {
                "prebuilt_voice_config": {
                    "voice_name": "Aoede"
                }
            }
        }
    }

    try:
        print(f"Connecting to Gemini Live API with model {model}...", flush=True)
        async with client.aio.live.connect(model=model, config=config) as session:
            print("Gemini Live session started successfully!", flush=True)
            
            # State for tracking response times
            state = {"last_input_time": None, "first_token_received": False}
            
            async def receive_from_client():
                try:
                    audio_buffer = bytearray()
                    buffer_start_time = time.time()
                    while True:
                        data = await websocket.receive()
                        if "bytes" in data:
                            if state["last_input_time"] is None:
                                state["last_input_time"] = time.time()
                                state["first_token_received"] = False
                                
                            audio_buffer.extend(data["bytes"])
                            
                            # Send every ~0.25 seconds (8000 bytes at 16kHz 16-bit mono)
                            if len(audio_buffer) >= 8000:
                                chunk = bytes(audio_buffer)
                                audio_buffer.clear()
                                
                                fill_time = time.time() - buffer_start_time
                                print(f"🎙️ [AUDIO_IN] Captured and buffered {len(chunk)} bytes from frontend in {fill_time:.3f} seconds. Forwarding to Gemini...", flush=True)
                                buffer_start_time = time.time()
                                
                                asyncio.create_task(
                                    session.send_realtime_input(
                                        audio=types.Blob(
                                            data=chunk,
                                            mime_type="audio/pcm;rate=16000"
                                        )
                                    )
                                )
                        elif "text" in data:
                            msg = json.loads(data["text"])
                            if msg.get("type") == "text":
                                if state["last_input_time"] is None:
                                    state["last_input_time"] = time.time()
                                    state["first_token_received"] = False
                                asyncio.create_task(session.send_realtime_input(text=msg["content"]))
                except WebSocketDisconnect:
                    print("Client disconnected via WebSocketDisconnect", flush=True)
                except Exception as e:
                    print(f"Error receiving from client: {e}", flush=True)
                    
            async def receive_from_gemini():
                try:
                    while True:
                        async for response in session.receive():
                            # Calculate time to first token/audio chunk
                            if state["last_input_time"] is not None and not state["first_token_received"]:
                                latency = time.time() - state["last_input_time"]
                                print(f"⏱️ [LATENCY] Time to first response: {latency:.3f} seconds", flush=True)
                                state["first_token_received"] = True
    
                            server_content = response.server_content
                            if server_content:
                                if server_content.model_turn:
                                    for part in server_content.model_turn.parts:
                                        if part.inline_data:
                                            await websocket.send_bytes(part.inline_data.data)
                                        if part.text:
                                            await websocket.send_json({"type": "transcript_chunk", "content": part.text})
                                        if part.function_call:
                                            func_name = part.function_call.name
                                            args = part.function_call.args
                                            print(f"Executing tool {func_name} with args {args}", flush=True)
                                            result = ""
                                            if func_name == "check_availability":
                                                result = check_availability(args.get("day", ""))
                                            elif func_name == "book_appointment":
                                                result = book_appointment(args.get("day", ""), args.get("time", ""), args.get("name", ""))
                                            elif func_name == "cancel_appointment":
                                                result = cancel_appointment(args.get("name", ""), args.get("day", ""), args.get("time", ""))
                                            elif func_name == "reschedule_appointment":
                                                result = reschedule_appointment(args.get("name", ""), args.get("old_day", ""), args.get("old_time", ""), args.get("new_day", ""), args.get("new_time", ""))
                                            
                                            
                                            print(f"Tool {func_name} returned: {result}", flush=True)
                                            asyncio.create_task(
                                                session.send_tool_response(
                                                    function_responses=[
                                                        types.FunctionResponse(
                                                            name=func_name,
                                                            response={"result": result}
                                                        )
                                                    ]
                                                )
                                            )
                                    
                                if server_content.turn_complete:
                                    state["last_input_time"] = None # Reset for next turn
                                    await websocket.send_json({"type": "transcript_complete"})
                except asyncio.CancelledError:
                    print("receive_from_gemini cancelled", flush=True)
                except Exception as e:
                    print(f"Error receiving from Gemini: {e}", flush=True)

            task1 = asyncio.create_task(receive_from_client())
            task2 = asyncio.create_task(receive_from_gemini())
            
            done, pending = await asyncio.wait(
                [task1, task2],
                return_when=asyncio.FIRST_COMPLETED
            )
            print(f"Tasks completed. Done: {done}", flush=True)
            for p in pending:
                p.cancel()
            
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"Gemini connection error: {e}", flush=True)
        try:
            await websocket.close()
        except:
            pass
