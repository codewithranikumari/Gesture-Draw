import threading
import time
from pathlib import Path

import cv2

from drawing import Drawing
from hand_tracking import HandTracker


CAMERA_INDEX = 0
GESTURE_HOLD_FRAMES = 5
RESUME_HOLD_SECONDS = 2.0
JPEG_QUALITY = 85


class DrawingStudio:

    def __init__(self):
        self._lock = threading.RLock()
        self._stop_event = None
        self._thread = None
        self._drawing = None
        self._latest_frame = None
        self._status = "idle"
        self._camera = "idle"
        self._hand_detected = False
        self._gesture = "none"
        self._message = "Read the gesture rules before starting the camera."
        self._error = None

    def start(self, confirmed):
        if confirmed is not True:
            raise ValueError("Confirm that you have read the gesture controls first.")

        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                if self._status == "stopping":
                    raise RuntimeError("The camera is still closing. Please wait a moment.")
                return self._state_locked()

            self._stop_event = threading.Event()
            self._drawing = Drawing()
            self._latest_frame = None
            self._status = "starting"
            self._camera = "requesting"
            self._hand_detected = False
            self._gesture = "none"
            self._error = None
            self._message = "Opening the camera..."
            self._thread = threading.Thread(
                target=self._capture_loop,
                args=(self._stop_event,),
                name="gesture-draw-camera",
                daemon=True
            )
            self._thread.start()
            return self._state_locked()

    def stop(self):
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                self._status = "idle"
                self._camera = "idle"
                self._latest_frame = None
                self._message = "Drawing studio closed."
                return self._state_locked()

            self._status = "stopping"
            self._message = "Closing the camera..."
            self._stop_event.set()
            return self._state_locked()

    def close(self):
        self.stop()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=3)

    def state(self):
        with self._lock:
            return self._state_locked()

    def latest_frame(self):
        with self._lock:
            return self._latest_frame

    def clear(self):
        with self._lock:
            drawing = self._require_running()
            drawing.clear()

    def select_color(self, index):
        with self._lock:
            drawing = self._require_running()
            drawing.select_color(index)

    def toggle_eraser(self):
        with self._lock:
            drawing = self._require_running()
            drawing.toggle_eraser()
            return self._state_locked()

    def save_artwork(self):
        with self._lock:
            drawing = self._require_running()
            if drawing.canvas is None or drawing.mask is None:
                raise RuntimeError("Draw something before saving your artwork.")
            image = cv2.cvtColor(drawing.canvas.copy(), cv2.COLOR_BGR2BGRA)
            image[:, :, 3] = drawing.mask.copy()

        output = Path(__file__).with_name("output")
        output.mkdir(exist_ok=True)
        path = output / f"gesture_draw_{time.strftime('%Y%m%d_%H%M%S')}.png"
        if not cv2.imwrite(str(path), image):
            raise RuntimeError("Could not save artwork to the output folder.")
        return path.name

    def _require_running(self):
        if self._status != "running" or self._drawing is None:
            raise RuntimeError("Start the drawing studio before using this control.")
        return self._drawing

    def _state_locked(self):
        drawing = self._drawing
        colors = []
        if drawing is not None:
            for name, (blue, green, red) in drawing.colors:
                colors.append({
                    "name": name,
                    "hex": f"#{red:02x}{green:02x}{blue:02x}"
                })
        return {
            "status": self._status,
            "camera": self._camera,
            "handDetected": self._hand_detected,
            "gesture": self._gesture,
            "message": self._message,
            "error": self._error,
            "colors": colors,
            "selectedColor": drawing.color_index if drawing is not None else None,
            "eraser": drawing.eraser_mode if drawing is not None else False
        }

    def _set_failure(self, message):
        with self._lock:
            self._status = "error"
            self._camera = "error"
            self._hand_detected = False
            self._gesture = "none"
            self._error = message
            self._message = message
            self._latest_frame = None

    def _capture_loop(self, stop_event):
        camera = None
        tracker = None
        fist_eraser = False
        open_palm_frames = 0
        open_palm_active = False
        horns_frames = 0
        waiting_for_hand = False
        resume_started_at = None

        try:
            camera = cv2.VideoCapture(CAMERA_INDEX)
            if not camera.isOpened():
                self._set_failure(
                    "Camera not found. Check camera permissions and make sure no other app is using it."
                )
                return

            tracker = HandTracker()
            with self._lock:
                self._status = "running"
                self._camera = "connected"
                self._message = "Camera connected. Show your palm to draw."

            while not stop_event.is_set():
                success, frame = camera.read()
                if not success:
                    self._set_failure("The camera stopped responding. Check its connection and try again.")
                    return

                frame = cv2.flip(frame, 1)
                hand = tracker.detect_hand(frame)
                point = None
                gesture = "none"

                sign_of_horns = hand is not None and tracker.is_sign_of_horns(hand, frame.shape)
                if waiting_for_hand:
                    if hand is not None and not sign_of_horns:
                        if resume_started_at is None:
                            resume_started_at = time.monotonic()
                        elif time.monotonic() - resume_started_at >= RESUME_HOLD_SECONDS:
                            waiting_for_hand = False
                            resume_started_at = None
                            with self._lock:
                                self._status = "running"
                                self._camera = "connected"
                                self._message = "Camera connected. Drawing resumed."
                    else:
                        resume_started_at = None
                    if waiting_for_hand:
                        gesture = "resume"
                elif sign_of_horns:
                    horns_frames += 1
                    gesture = "exit"
                    if horns_frames >= GESTURE_HOLD_FRAMES:
                        with self._lock:
                            self._status = "standby"
                            self._camera = "connected"
                            self._message = (
                                "Camera stays active in standby. Hold a non-horns hand gesture for "
                                "2 seconds to restart, or exit home to turn it off."
                            )
                            self._latest_frame = None
                        waiting_for_hand = True
                        resume_started_at = None
                        horns_frames = 0
                        gesture = "resume"
                else:
                    horns_frames = 0

                if hand and not sign_of_horns and not waiting_for_hand:
                    height, width = frame.shape[:2]
                    index = hand.landmark[8]
                    thumb = hand.landmark[4]
                    point = (int(index.x * width), int(index.y * height))

                    if tracker.is_open_palm(hand):
                        gesture = "color"
                        open_palm_frames += 1
                        point = None
                        if open_palm_frames >= GESTURE_HOLD_FRAMES and not open_palm_active:
                            with self._lock:
                                self._drawing.cycle_color()
                            open_palm_active = True
                    else:
                        open_palm_frames = 0
                        open_palm_active = False

                        if tracker.is_fist(hand):
                            gesture = "erase"
                            if not fist_eraser:
                                with self._lock:
                                    self._drawing.set_eraser(True)
                                fist_eraser = True
                        else:
                            if fist_eraser:
                                with self._lock:
                                    self._drawing.set_eraser(False)
                                fist_eraser = False

                            tx = int(thumb.x * width)
                            ty = int(thumb.y * height)
                            distance = ((point[0] - tx) ** 2 + (point[1] - ty) ** 2) ** 0.5
                            if distance <= 40:
                                gesture = "pause"
                                point = None
                            else:
                                gesture = "draw"
                else:
                    open_palm_frames = 0
                    open_palm_active = False
                    if fist_eraser:
                        with self._lock:
                            self._drawing.set_eraser(False)
                        fist_eraser = False

                with self._lock:
                    result = self._drawing.draw(frame, point)
                    self._hand_detected = hand is not None
                    self._gesture = "resume" if waiting_for_hand else gesture
                    if waiting_for_hand:
                        self._latest_frame = None
                    else:
                        encoded, buffer = cv2.imencode(
                            ".jpg",
                            result,
                            [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY]
                        )
                        if encoded:
                            self._latest_frame = buffer.tobytes()
        except (cv2.error, RuntimeError, ValueError, OSError) as error:
            self._set_failure(f"Drawing studio error: {error}")
        finally:
            if camera is not None:
                camera.release()
            if tracker is not None:
                tracker.close()
            with self._lock:
                self._latest_frame = None
                if self._status != "error":
                    self._status = "idle"
                    self._camera = "idle"
                    self._hand_detected = False
                    self._gesture = "none"
                    self._message = "Drawing studio closed."
