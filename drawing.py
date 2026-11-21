import cv2


class Drawing:

    def __init__(self):

        self.canvas = None
        self.mask = None
        self.previous_point = None
        self.colors = [
            ("Magenta", (255, 0, 255)),
            ("Cyan", (255, 255, 0)),
            ("Green", (0, 255, 0)),
            ("Yellow", (0, 255, 255)),
            ("Blue", (255, 0, 0)),
            ("Red", (0, 0, 255)),
            ("Black", (0, 0, 0))
        ]
        self.color_index = 0
        self.color_name, self.color = self.colors[self.color_index]
        self.brush_size = 10
        self.eraser_size = 56
        self.eraser_mode = False

    def draw(self, frame, point):

        if self.canvas is None:
            self.canvas = frame.copy()
            self.canvas[:] = 0
            self.mask = cv2.cvtColor(self.canvas, cv2.COLOR_BGR2GRAY)

        if point is not None:
            color = (0, 0, 0) if self.eraser_mode else self.color
            thickness = self.eraser_size if self.eraser_mode else self.brush_size
            mask_color = 0 if self.eraser_mode else 255

            if self.previous_point is None:
                cv2.circle(self.canvas, point, thickness // 2, color, -1)
                cv2.circle(self.mask, point, thickness // 2, mask_color, -1)
            else:
                cv2.line(self.canvas, self.previous_point, point, color, thickness)
                cv2.line(self.mask, self.previous_point, point, mask_color, thickness)

            self.previous_point = point
        else:
            self.previous_point = None

        alpha = self.mask.astype("float32")[:, :, None] / 255
        return (
            frame.astype("float32") * (1 - alpha)
            + self.canvas.astype("float32") * alpha
        ).astype("uint8")

    def cycle_color(self):

        self.color_index = (self.color_index + 1) % len(self.colors)
        self.color_name, self.color = self.colors[self.color_index]
        self.set_eraser(False)

    def select_color(self, index):

        if type(index) is not int or not 0 <= index < len(self.colors):
            raise ValueError("Invalid color selection.")

        self.color_index = index
        self.color_name, self.color = self.colors[index]
        self.set_eraser(False)

    def toggle_eraser(self):

        self.set_eraser(not self.eraser_mode)

    def set_eraser(self, enabled):

        self.eraser_mode = enabled
        self.previous_point = None

    def clear(self):

        if self.canvas is not None:
            self.canvas[:] = 0
            self.mask[:] = 0
        self.previous_point = None
