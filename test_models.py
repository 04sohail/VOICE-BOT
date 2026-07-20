import asyncio
import os
from google import genai
from dotenv import load_dotenv

load_dotenv()

async def test_live():
    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    for model in client.models.list():
        if "gemini" in model.name:
            print(model.name, model.supported_actions)

asyncio.run(test_live())
