import math

import cv2
import mediapipe as mp


class HandTracker:

    def __init__(self):

        self.mp_hands = mp.solutions.hands

        self.hands = self.mp_hands.Hands(
            max_num_hands=1,
            min_detection_confidence=0.7,
            min_tracking_confidence=0.7
        )

        self.mp_draw = mp.solutions.drawing_utils

    def detect_hand(self, frame):

        rgb = cv2.cvtColor(
            frame,
            cv2.COLOR_BGR2RGB
        )

        results = self.hands.process(rgb)

        if results.multi_hand_landmarks:

            for hand in results.multi_hand_landmarks:

                self.mp_draw.draw_landmarks(
                    frame,
                    hand,
                    self.mp_hands.HAND_CONNECTIONS
                )

                return hand

        return None

    def is_fist(self, hand):

        landmarks = hand.landmark
        finger_pairs = ((8, 6), (12, 10), (16, 14), (20, 18))
        return not any(
            landmarks[tip].y < landmarks[pip].y
            for tip, pip in finger_pairs
        )

    def is_open_palm(self, hand):

        landmarks = hand.landmark
        finger_pairs = ((8, 6), (12, 10), (16, 14), (20, 18))
        return all(
            landmarks[tip].y < landmarks[pip].y
            for tip, pip in finger_pairs
        )

    def close(self):

        self.hands.close()

    def is_sign_of_horns(self, hand, frame_shape=None):

        landmarks = hand.landmark
        height, width = frame_shape[:2] if frame_shape is not None else (1, 1)

        def point(index):
            landmark = landmarks[index]
            return (landmark.x * width, landmark.y * height, landmark.z * width)

        def distance(first, second):
            return math.sqrt(sum((a - b) ** 2 for a, b in zip(first, second)))

        def joint_angle(mcp, pip, dip):
            center = point(pip)
            first = tuple(a - b for a, b in zip(point(mcp), center))
            second = tuple(a - b for a, b in zip(point(dip), center))
            first_length = math.sqrt(sum(value ** 2 for value in first))
            second_length = math.sqrt(sum(value ** 2 for value in second))
            if first_length == 0 or second_length == 0:
                return 0
            cosine = sum(a * b for a, b in zip(first, second)) / (first_length * second_length)
            return math.degrees(math.acos(max(-1.0, min(1.0, cosine))))

        def extended(mcp, pip, dip, tip):
            return (
                joint_angle(mcp, pip, dip) > 140
                and distance(point(0), point(tip)) > distance(point(0), point(pip)) * 1.08
            )

        def folded(mcp, pip, dip):
            return joint_angle(mcp, pip, dip) < 140

        return (
            extended(5, 6, 7, 8)
            and folded(9, 10, 11)
            and folded(13, 14, 15)
            and extended(17, 18, 19, 20)
        )
