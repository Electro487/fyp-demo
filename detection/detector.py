import cv2
import json
import os
import sys
import time
import requests
import threading
import numpy as np
from ultralytics import YOLO

class ShotJpgStream:
    """Fast snapshot stream wrapper for IP Webcam /shot.jpg."""
    def __init__(self, shot_url):
        self.url = shot_url
        self.running = True
        self.ret = False
        self.frame = None
        self.lock = threading.Lock()
        self._fetch_frame()
        if self.ret:
            self.thread = threading.Thread(target=self._update_loop, daemon=True)
            self.thread.start()

    def _fetch_frame(self):
        try:
            resp = requests.get(self.url, timeout=1.0)
            if resp.status_code == 200:
                arr = np.frombuffer(resp.content, dtype=np.uint8)
                img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                if img is not None:
                    with self.lock:
                        self.frame = img
                        self.ret = True
                    return True
        except Exception:
            pass
        return False

    def _update_loop(self):
        while self.running:
            self._fetch_frame()
            time.sleep(0.015)

    def read(self):
        with self.lock:
            if self.frame is None:
                return False, None
            return self.ret, self.frame.copy()

    def isOpened(self):
        return self.ret

    def release(self):
        self.running = False

class OpenCVFastStream:
    """
    High-speed OpenCV stream wrapper using cap.grab() + cap.retrieve().
    Flushes internal FFmpeg socket buffers at 30+ FPS for instant state transitions.
    """
    def __init__(self, src):
        self.cap = cv2.VideoCapture(src)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self.ret = False
        self.frame = None
        self.running = True
        self.lock = threading.Lock()

        if self.cap.isOpened():
            ret, frame = self.cap.read()
            if ret:
                self.ret = ret
                self.frame = frame
            self.thread = threading.Thread(target=self._update_loop, daemon=True)
            self.thread.start()

    def _update_loop(self):
        while self.running and self.cap.isOpened():
            # grab() instantly discards stale queued buffer frames in < 1ms
            grabbed = self.cap.grab()
            if grabbed:
                ret, frame = self.cap.retrieve()
                if ret:
                    with self.lock:
                        self.ret = ret
                        self.frame = frame
            else:
                time.sleep(0.005)

    def read(self):
        with self.lock:
            if self.frame is None:
                return False, None
            return self.ret, self.frame.copy()

    def isOpened(self):
        return self.cap.isOpened()

    def release(self):
        self.running = False
        if self.cap:
            self.cap.release()

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "seats_config.json")

def load_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r") as f:
            return json.load(f)
    return {
        "stream_url": "http://192.168.1.71:8080/video",
        "backend_url": "http://localhost:8000",
        "debounce_frames": 5,
        "confidence_threshold": 0.4,
        "seats": []
    }

def send_update_to_backend(backend_url, seats_status):
    """Post updated seat status dictionary asynchronously without blocking the main OpenCV video loop."""
    def _async_post():
        try:
            url = f"{backend_url.rstrip('/')}/api/seats/update"
            payload = {"seats": seats_status}
            requests.post(url, json=payload, timeout=1.5)
        except Exception:
            pass
    threading.Thread(target=_async_post, daemon=True).start()

def get_pixel_polygon(polygon_data, frame_w, frame_h):
    """
    Converts polygon coordinates (normalized 0..1 or legacy pixels) to actual pixel coordinates for frame.
    """
    pixel_pts = []
    for pt in polygon_data:
        x, y = pt[0], pt[1]
        if x <= 1.0 and y <= 1.0:
            px = int(x * frame_w)
            py = int(y * frame_h)
        else:
            px = int(x)
            py = int(y)
        pixel_pts.append([px, py])
    return np.array(pixel_pts, np.int32)

def main():
    config = load_config()
    raw_stream_url = config.get("stream_url", "http://192.168.1.71:8080/video")
    backend_url = config.get("backend_url", "http://localhost:8000")
    debounce_frames = config.get("debounce_frames", 5)
    conf_thresh = config.get("confidence_threshold", 0.4)
    seats = config.get("seats", [])

    print("\n========================================================")
    print("      YOLOV8 REAL-TIME SEAT OCCUPANCY DETECTOR          ")
    print("========================================================")
    print(f"Target Stream: {raw_stream_url}")
    print(f"Backend API: {backend_url}")
    print(f"Debounce Threshold: {debounce_frames} frames")
    print(f"Total Seat Zones: {len(seats)}")
    print("========================================================\n")

    print("Loading YOLOv8 model (yolov8n.pt)...")
    try:
        model = YOLO("yolov8n.pt")
        import torch
        if torch.cuda.is_available():
            print(f"[GPU ACTIVE] Running YOLOv8 on GPU: {torch.cuda.get_device_name(0)}")
            model.to('cuda')
        else:
            print("[CPU MODE] GPU not detected. Running YOLOv8 on CPU.")
    except Exception as e:
        print(f"[ERROR] Failed to load YOLOv8 model: {e}")
        sys.exit(1)

    cap = None
    if "8080" in str(raw_stream_url) and ("video" in str(raw_stream_url) or "greet" in str(raw_stream_url)):
        shot_url = str(raw_stream_url).replace("/video", "/shot.jpg").replace("/greet.html", "/shot.jpg")
        if not shot_url.endswith("/shot.jpg"):
            shot_url = shot_url.rstrip("/") + "/shot.jpg"
        print(f"[HIGH SPEED STREAM] Using IP Webcam snapshot mode: {shot_url}")
        cap = ShotJpgStream(shot_url)

    if cap is None or not cap.isOpened():
        print(f"Opening video capture stream: {raw_stream_url}")
        cap = OpenCVFastStream(raw_stream_url)
        if not cap.isOpened():
            print(f"[WARNING] Stream URL unreachable. Falling back to local camera (0)...")
            cap = OpenCVFastStream(0)

    if not cap or not cap.isOpened():
        print("[ERROR] Cannot access video source. Exiting.")
        sys.exit(1)

    confirmed_states = {s["id"]: "VACANT" for s in seats}
    raw_counters = {s["id"]: {"pending_state": "VACANT", "count": 0} for s in seats}

    if seats:
        send_update_to_backend(backend_url, confirmed_states)

    fps_count = 0
    start_time = time.time()
    fps = 0.0

    window_name = "Real-Time Seat Occupancy Detection (YOLOv8 + OpenCV)"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)

    while True:
        ret, frame = cap.read()
        if not ret or frame is None:
            time.sleep(0.01)
            continue

        fh, fw = frame.shape[:2]

        fps_count += 1
        if time.time() - start_time >= 1.0:
            fps = fps_count / (time.time() - start_time)
            fps_count = 0
            start_time = time.time()

        # Run YOLOv8 detection
        results = model(frame, verbose=False, conf=conf_thresh)[0]

        person_boxes = []
        for box in results.boxes:
            cls_id = int(box.cls[0].item())
            if cls_id == 0:
                coords = box.xyxy[0].cpu().numpy().astype(int)
                conf = float(box.conf[0].item())
                person_boxes.append((coords, conf))

        # Test occupancy for each seat zone
        raw_frame_occupancy = {s["id"]: False for s in seats}

        for seat in seats:
            seat_id = seat["id"]
            polygon_pixel = get_pixel_polygon(seat["polygon"], fw, fh)
            if len(polygon_pixel) < 3:
                continue

            for (x1, y1, x2, y2), conf in person_boxes:
                cx = (x1 + x2) // 2
                cy = y2 - int((y2 - y1) * 0.15)
                inside = cv2.pointPolygonTest(polygon_pixel, (float(cx), float(cy)), False) >= 0
                if not inside:
                    inside = cv2.pointPolygonTest(polygon_pixel, (float(cx), float((y1+y2)//2)), False) >= 0

                if inside:
                    raw_frame_occupancy[seat_id] = True
                    break

        # Apply Debounce Logic
        state_changed = False
        for seat in seats:
            seat_id = seat["id"]
            raw_state = "OCCUPIED" if raw_frame_occupancy[seat_id] else "VACANT"
            current_confirmed = confirmed_states[seat_id]

            if raw_state != current_confirmed:
                if raw_counters[seat_id]["pending_state"] == raw_state:
                    raw_counters[seat_id]["count"] += 1
                else:
                    raw_counters[seat_id]["pending_state"] = raw_state
                    raw_counters[seat_id]["count"] = 1

                if raw_counters[seat_id]["count"] >= debounce_frames:
                    confirmed_states[seat_id] = raw_state
                    raw_counters[seat_id]["count"] = 0
                    state_changed = True
                    print(f"[STATE CHANGE] Seat {seat_id} ({seat.get('name')}) is now {raw_state}")
            else:
                raw_counters[seat_id]["count"] = 0
                raw_counters[seat_id]["pending_state"] = current_confirmed

        if state_changed:
            send_update_to_backend(backend_url, confirmed_states)

        # Build Visual Overlay Frame
        display_frame = frame.copy()

        # Draw Seat Zones
        for seat in seats:
            seat_id = seat["id"]
            polygon_pixel = get_pixel_polygon(seat["polygon"], fw, fh).reshape((-1, 1, 2))
            is_occupied = (confirmed_states.get(seat_id) == "OCCUPIED")

            color = (40, 40, 230) if is_occupied else (0, 220, 100)

            overlay = display_frame.copy()
            cv2.fillPoly(overlay, [polygon_pixel], color)
            cv2.addWeighted(overlay, 0.35, display_frame, 0.65, 0, display_frame)
            cv2.polylines(display_frame, [polygon_pixel], isClosed=True, color=color, thickness=3)

            if len(seat["polygon"]) > 0:
                first_pt = polygon_pixel[0][0]
                lx, ly = first_pt[0], first_pt[1]
                label = f"{seat['name']}: {confirmed_states.get(seat_id, 'VACANT')}"
                cv2.rectangle(display_frame, (lx, max(30, ly - 30)), (lx + 220, max(30, ly)), (0, 0, 0), -1)
                cv2.putText(display_frame, label, (lx + 10, max(20, ly - 10)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)

        # Draw person detection bounding boxes
        for (x1, y1, x2, y2), conf in person_boxes:
            cv2.rectangle(display_frame, (x1, y1), (x2, y2), (255, 200, 0), 2)
            cv2.putText(display_frame, f"Person {conf:.2f}", (x1, max(20, y1 - 10)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 200, 0), 2)

        # On-Screen HUD Dashboard
        hud = display_frame.copy()
        cv2.rectangle(hud, (10, 10), (450, 85), (15, 15, 25), -1)
        display_frame = cv2.addWeighted(hud, 0.75, display_frame, 0.25, 0)

        occupied_count = sum(1 for st in confirmed_states.values() if st == "OCCUPIED")
        total_seats = len(seats)

        cv2.putText(display_frame, f"Occupancy: {occupied_count}/{total_seats} Occupied", (20, 35),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2)
        cv2.putText(display_frame, f"FPS: {fps:.1f} | Frame: {fw}x{fh}", (20, 65),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)

        cv2.imshow(window_name, display_frame)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            print("Stopping detection loop.")
            break

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
