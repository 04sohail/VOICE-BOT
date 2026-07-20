import os
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from services.graph.workflow import app


async def generate_response(chat_history: list):
    """
    Takes the raw chat history, updates our LangGraph state, and streams the response.
    """

    latest_msg = chat_history[-1] if chat_history else None
    if not latest_msg or latest_msg["role"] != "user":
        return

    user_message = HumanMessage(content=latest_msg["content"])
    input_state = {"messages": [user_message]}

    config = {"configurable": {"thread_id": "user_session_1"}}

    try:
        print("[LLM] Starting LangGraph stream...", flush=True)
        # Stream output directly from the nodes (tokens)
        async for chunk, metadata in app.astream(
            input_state, config, stream_mode="messages"
        ):
            print(f"[LLM] Yielded chunk type: {type(chunk)}", flush=True)
            # Only stream AIMessages back to the user
            if getattr(chunk, "type", "") == "ai" and chunk.content:
                yield chunk.content

        # The Checkpointer automatically saves the updated state internally!

    except Exception as e:
        print(f"LangGraph Error: {e}")
        import traceback

        traceback.print_exc()
        yield "I'm sorry, my computer system is having trouble right now."
