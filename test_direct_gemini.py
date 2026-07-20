import asyncio
import os
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

async def test_live():
    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-native-audio-latest")
    
    config = {
        "response_modalities": ["AUDIO"],
    }
    
    try:
        print(f"Connecting to Gemini Live API with model {model}...")
        async with client.aio.live.connect(model=model, config=config) as session:
            print("Connected!")
            
            # Send text
            await session.send_realtime_input(text="Hello!")
            
            while True:
                print("Calling session.receive()...")
                async for response in session.receive():
                    if response.server_content:
                        if response.server_content.model_turn:
                            print("Received model_turn part")
                        if response.server_content.turn_complete:
                            print("Turn complete!")
                print("session.receive() finished naturally. Let's send another message!")
                await session.send_realtime_input(text="Are you still there?")
    except Exception as e:
        print(f"Error: {e}")

asyncio.run(test_live())
