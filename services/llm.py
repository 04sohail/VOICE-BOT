import os
from openai import AsyncOpenAI


async def generate_response(chat_history: list):
    client = AsyncOpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=os.getenv("OPENROUTER_API_KEY", "dummy_key"),
    )

    try:
        response = await client.chat.completions.create(
            model="openai/gpt-4o-mini", messages=chat_history, stream=True
        )

        async for chunk in response:
            if chunk.choices and chunk.choices[0].delta.content is not None:
                yield chunk.choices[0].delta.content
    except Exception as e:
        print(f"LLM Error: {e}")
        yield "I'm sorry, I'm having trouble connecting to my brain right now."
