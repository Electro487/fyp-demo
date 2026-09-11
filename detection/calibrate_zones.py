import cv2
import json
import os
import sys
import time
import requests
import threading
import numpy as np

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
            time.sleep(0.02)

    def read(self):
        with self.lock:
            if self.frame is None:
                return False, None
            return self.ret, self.frame.copy()

    def isOpened(self):
        return self.ret

    def release(self):
        self.running = False

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "seats_config.json")

def load_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r") as f:
            return json.load(f)
    return {
        "stream_url": "http://192.168.1.71:8080/video",
        "seats": [
            {"id": 1, "name": "Seat A (Left)", "polygon": []},
            {"id": 2, "name": "Seat B (Center)", "polygon": []},
            {"id": 3, "name": "Seat C (Right)", "polygon": []}
        ]
    }

def save_config(config_data):
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(config_data, f, indent=2)
    print(f"\n[SUCCESS] Resolution-independent configuration saved to {os.path.abspath(CONFIG_PATH)}")

current_seat_idx = 0
current_points_pixel = []
all_seat_polygons_norm = [[], [], []]
frame_dimensions = (1280, 720) # (width, height)

def mouse_callback(event, x, y, flags, param):
    global current_points_pixel, current_seat_idx, all_seat_polygons_norm, frame_dimensions
    fw, fh = frame_dimensions
    if event == cv2.EVENT_LBUTTONDOWN:
        if len(current_points_pixel) < 4 and current_seat_idx < 3:
            current_points_pixel.append([x, y])
            norm_x = round(x / float(fw), 4)
            norm_y = round(y / float(fh), 4)
            print(f"Seat {current_seat_idx + 1} Point {len(current_points_pixel)}: Pixel({x},{y}) -> Normalized({norm_x}, {norm_y})")
            
            if len(current_points_pixel) == 4:
                # Save normalized points
                norm_poly = [[round(px / float(fw), 4), round(py / float(fh), 4)] for px, py in current_points_pixel]
                all_seat_polygons_norm[current_seat_idx] = norm_poly
                print(f"-> Seat {current_seat_idx + 1} zone completed!")
                current_seat_idx += 1
                current_points_pixel = []

def main():
    global current_seat_idx, current_points_pixel, all_seat_polygons_norm, frame_dimensions
    config = load_config()
    raw_stream_url = config.get("stream_url", "http://192.168.1.71:8080/video")

    print("\n========================================================")
    print("  RESOLUTION-INDEPENDENT SEAT CALIBRATION TOOL          ")
    print("========================================================")
    print("Instructions:")
    print("1. Click 4 corner points on the video feed to define each seat.")
    print("2. Define Seat 1, then Seat 2, then Seat 3.")
    print("3. Press 'R' to reset points for the current seat.")
    print("4. Press 'S' to save normalized configuration to JSON.")
    print("5. Press 'Q' to exit.\n")

    cap = None
    if "8080" in str(raw_stream_url) and ("video" in str(raw_stream_url) or "greet" in str(raw_stream_url)):
        shot_url = str(raw_stream_url).replace("/video", "/shot.jpg").replace("/greet.html", "/shot.jpg")
        if not shot_url.endswith("/shot.jpg"):
            shot_url = shot_url.rstrip("/") + "/shot.jpg"
        print(f"Connecting via IP Webcam snapshot mode: {shot_url}")
        cap = ShotJpgStream(shot_url)

    if cap is None or not cap.isOpened():
        print(f"Connecting to video stream: {raw_stream_url}")
        cap = cv2.VideoCapture(raw_stream_url)
        if not cap.isOpened():
            print(f"[WARNING] Could not open stream {raw_stream_url}. Falling back to default webcam (0)...")
            cap = cv2.VideoCapture(0)

    if not cap or not cap.isOpened():
        print("[ERROR] Failed to open video source. Exiting.")
        sys.exit(1)

    window_name = "Seat Calibration - Click 4 points per seat"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.setMouseCallback(window_name, mouse_callback)

    colors = [(0, 255, 0), (255, 255, 0), (0, 165, 255)]

    existing_seats = config.get("seats", [])
    for idx, s in enumerate(existing_seats):
        if idx < 3 and "polygon" in s and len(s["polygon"]) == 4:
            all_seat_polygons_norm[idx] = s["polygon"]

    while True:
        ret, frame = cap.read()
        if not ret or frame is None:
            time.sleep(0.02)
            continue

        fh, fw = frame.shape[:2]
        frame_dimensions = (fw, fh)

        display_frame = frame.copy()

        # Draw existing saved polygons (convert normalized to current frame pixels)
        for idx, poly in enumerate(all_seat_polygons_norm):
            if len(poly) == 4:
                # Convert normalized [0..1] to pixel coords
                pixel_poly = []
                for pt in poly:
                    if pt[0] <= 1.0 and pt[1] <= 1.0:
                        px = int(pt[0] * fw)
                        py = int(pt[1] * fh)
                    else:
                        px, py = int(pt[0]), int(pt[1])
                    pixel_poly.append([px, py])

                pts = np.array(pixel_poly, np.int32).reshape((-1, 1, 2))
                cv2.polylines(display_frame, [pts], isClosed=True, color=colors[idx], thickness=2)
                cv2.putText(display_frame, f"Seat {idx+1}", (pixel_poly[0][0], max(20, pixel_poly[0][1] - 10)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, colors[idx], 2)

        # Draw points currently being clicked
        for pt in current_points_pixel:
            cv2.circle(display_frame, (pt[0], pt[1]), 5, (0, 0, 255), -1)
        if len(current_points_pixel) > 1:
            pts = np.array(current_points_pixel, np.int32).reshape((-1, 1, 2))
            cv2.polylines(display_frame, [pts], isClosed=False, color=(0, 0, 255), thickness=1)

        # HUD Instructions
        hud_bg = display_frame.copy()
        cv2.rectangle(hud_bg, (10, 10), (580, 90), (0, 0, 0), -1)
        display_frame = cv2.addWeighted(hud_bg, 0.65, display_frame, 0.35, 0)

        if current_seat_idx < 3:
            status_text = f"Defining Seat {current_seat_idx + 1}/3 - Click point {len(current_points_pixel) + 1}/4"
        else:
            status_text = "All 3 Seats defined! Press 'S' to Save or 'R' to Reset."

        cv2.putText(display_frame, status_text, (20, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        cv2.putText(display_frame, f"[S] Save  |  [R] Reset  |  [Q] Quit  | Frame: {fw}x{fh}", (20, 70),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)

        cv2.imshow(window_name, display_frame)
        key = cv2.waitKey(20) & 0xFF

        if key == ord('q'):
            print("Exiting calibration without saving.")
            break
        elif key == ord('r'):
            current_points_pixel = []
            if current_seat_idx > 0:
                current_seat_idx -= 1
                all_seat_polygons_norm[current_seat_idx] = []
            print(f"Resetting points for Seat {current_seat_idx + 1}")
        elif key == ord('s'):
            if all_seat_polygons_norm[0] and all_seat_polygons_norm[1] and all_seat_polygons_norm[2]:
                for idx in range(3):
                    config["seats"][idx]["polygon"] = all_seat_polygons_norm[idx]
                save_config(config)
                print("Normalized configuration successfully saved!")
                break
            else:
                print("[WARNING] Please define all 3 seat polygons before saving!")

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
