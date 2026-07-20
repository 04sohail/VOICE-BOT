import asyncio
import websockets
import json

async def test_connection():
    uri = "ws://localhost:8000/ws"
    print(f"Connecting to {uri}...")
    try:
        async with websockets.connect(uri) as websocket:
            print("Successfully connected to FastAPI WebSocket endpoint!")
            
            test_msg = json.dumps({"type": "text", "content": "Say 'hello world' and nothing else."})
            print(f"Sending message: {test_msg}")
            await websocket.send(test_msg)
            
            print("Waiting for response...")
            audio_chunks = 0
            while True:
                try:
                    msg = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                    if isinstance(msg, bytes):
                        audio_chunks += 1
                    else:
                        print(f"Received text data: {msg}")
                        if "transcript_complete" in msg:
                            print(f"Received {audio_chunks} audio chunks.")
                            print("Waiting 5 seconds to see if connection stays open...")
                            await asyncio.sleep(5)
                            print("Sending second message...")
                            await websocket.send(json.dumps({"type": "text", "content": "Are you still there?"}))
                except asyncio.TimeoutError:
                    print(f"Timeout (5s). Audio chunks so far: {audio_chunks}. Connection still open.")
                    break
                
    except websockets.exceptions.ConnectionClosed as e:
        print(f"Connection closed prematurely: {e}")
    except Exception as e:
        print(f"Unexpected error: {e}")

if __name__ == "__main__":
    asyncio.run(test_connection())
