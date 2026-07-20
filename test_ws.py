import asyncio
import websockets

async def test():
    async with websockets.connect('ws://localhost:8081/ws') as websocket:
        print("Connected")
        try:
            msg = await websocket.recv()
            print(f"Received: {msg}")
        except Exception as e:
            print(f"Error: {e}")

asyncio.run(test())
