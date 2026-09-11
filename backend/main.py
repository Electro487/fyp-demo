import asyncio
import logging
from typing import Dict, List, Any
from datetime import datetime
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# Set up logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("SeatBackend")

app = FastAPI(
    title="Seat Occupancy API & WebSocket Manager",
    description="Backend service for broadcasting real-time seat occupancy detection",
    version="1.0.0"
)

# Enable CORS for local and remote visualizer frontends
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Data Schemas
class SeatStateUpdate(BaseModel):
    seat_id: int = Field(..., description="ID of the seat (1, 2, 3)")
    state: str = Field(..., description="State: 'OCCUPIED' or 'VACANT'")

class BulkSeatUpdate(BaseModel):
    seats: Dict[int, str] = Field(..., description="Map of seat_id to state ('OCCUPIED' / 'VACANT')")

# In-memory storage for seat states
seat_states: Dict[int, Dict[str, Any]] = {
    1: {"id": 1, "name": "Seat A (Left)", "state": "VACANT", "updated_at": datetime.now().isoformat()},
    2: {"id": 2, "name": "Seat B (Center)", "state": "VACANT", "updated_at": datetime.now().isoformat()},
    3: {"id": 3, "name": "Seat C (Right)", "state": "VACANT", "updated_at": datetime.now().isoformat()}
}

# WebSocket Connection Manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"WebSocket client connected. Total clients: {len(self.active_connections)}")
        # Send initial snapshot of all seat states
        snapshot = {
            "type": "SNAPSHOT",
            "data": list(seat_states.values()),
            "timestamp": datetime.now().isoformat()
        }
        await websocket.send_json(snapshot)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info(f"WebSocket client disconnected. Remaining clients: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.warning(f"Error sending message to client: {e}")
                disconnected.append(connection)
        for conn in disconnected:
            self.disconnect(conn)

manager = ConnectionManager()

@app.get("/")
def read_root():
    return {
        "status": "online",
        "service": "Seat Occupancy Detection Backend",
        "seats_count": len(seat_states),
        "timestamp": datetime.now().isoformat()
    }

@app.get("/api/seats")
def get_all_seats():
    """Retrieve current states of all seat zones."""
    return list(seat_states.values())

@app.post("/api/seats/update")
async def update_seat(payload: BulkSeatUpdate):
    """
    Ingest bulk seat occupancy status updates from the CV Detector module.
    Broadcast updates to all connected 3D Web Visualizer clients via WebSockets.
    """
    changed = False
    now_str = datetime.now().isoformat()
    
    for seat_id, state in payload.seats.items():
        seat_id = int(seat_id)
        if seat_id in seat_states:
            if seat_states[seat_id]["state"] != state:
                seat_states[seat_id]["state"] = state
                seat_states[seat_id]["updated_at"] = now_str
                changed = True
        else:
            seat_states[seat_id] = {
                "id": seat_id,
                "name": f"Seat {seat_id}",
                "state": state,
                "updated_at": now_str
            }
            changed = True

    # Broadcast update event if states changed or periodically
    event_payload = {
        "type": "SEAT_UPDATE",
        "data": list(seat_states.values()),
        "timestamp": now_str
    }
    await manager.broadcast(event_payload)
    return {"status": "success", "seats": list(seat_states.values())}

@app.post("/api/seats/{seat_id}/toggle")
async def toggle_seat(seat_id: int):
    """Helper endpoint to manually toggle seat state for testing."""
    if seat_id not in seat_states:
        raise HTTPException(status_code=404, detail="Seat ID not found")
    
    current_state = seat_states[seat_id]["state"]
    new_state = "OCCUPIED" if current_state == "VACANT" else "VACANT"
    seat_states[seat_id]["state"] = new_state
    seat_states[seat_id]["updated_at"] = datetime.now().isoformat()

    event_payload = {
        "type": "SEAT_UPDATE",
        "data": list(seat_states.values()),
        "timestamp": datetime.now().isoformat()
    }
    await manager.broadcast(event_payload)
    return {"status": "success", "seat": seat_states[seat_id]}

@app.websocket("/ws/seats")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # Keep connection alive and listen for client ping/messages
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_json({"type": "pong", "timestamp": datetime.now().isoformat()})
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket exception: {e}")
        manager.disconnect(websocket)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
