import sensor
import time
import math
from machine import LED

sensor.reset()
sensor.set_pixformat(sensor.RGB565) #RGB565 #GRAYSCALE
sensor.set_framesize(sensor.QQVGA)
sensor.skip_frames(time=2000)
sensor.set_auto_gain(False)  # must turn this off to prevent image washout...
sensor.set_auto_whitebal(False)  # must turn this off to prevent image washout...

clock = time.clock()


# ------------------------------ Consts ------------------------------------------
scale = 1
f_x = (2.8 / 3.984) * 160 * scale  # find_apriltags defaults to this if not set
f_y = (2.8 / 2.952) * 120 * scale  # find_apriltags defaults to this if not set
c_x = 160 * 0.5 * scale  # find_apriltags defaults to this if not set (the image.w * 0.5)
c_y = 120 * 0.5 * scale  # find_apriltags defaults to this if not set (the image.h * 0.5)


TAG_SIZE_MM = 35


# ------------------------------ Functions ------------------------------------------
def normalize(angle, size=math.pi):
    while angle > size:
        angle -= 2 * size
    while angle < -size:
        angle += 2 * size
    return angle


def cam_to_robot(x_cam, z_cam, ry_cam):
    xC = [0.003303709761, -0.07393090644, 0.0004704518466, 0.0006506052901, 1.894870689, -0.5808105161, -0.0519523516, 183.7564033]
    yC = [0.009496728877, 0.01763352554, 0.0007779367, -0.0003346421788, -7.714126469, 0.429991588, 0.1082857274, 94.63788805]
    ryC = [-0.0004904404576, -0.001149986916, -0.00008486238749, 0.00004269535982, 1.610164906, -0.05456745533, -0.0840694127, -18.29406829]

    def sum(consts):
        ret = 0
        ret += consts[0] * ry_cam * z_cam
        ret += consts[1] * ry_cam * ry_cam
        ret += consts[2] * z_cam * z_cam
        ret += consts[3] * x_cam * x_cam
        ret += consts[4] * ry_cam
        ret += consts[5] * z_cam
        ret += consts[6] * x_cam
        return ret

    x = sum(xC)
    y = sum(yC)
    ry = sum(ryC)
    return x, y, ry


# ------------------------------ Tags ------------------------------------------
class Tag:
    def __init__(self, alpha=0.15, timeout_ms=100):
        # Moving Avrage
        self._moveing_avrage = None
        self.alpha = alpha
        # Lost Tag
        self._last_seen = None
        self.timeout_ms = timeout_ms
        # ID
        self.id = None
        # Transform
        self.tx = None
        self.tz = None
        # Rotation
        self.rx = None
        self.ry = None
        self.rz = None
        # Center
        self.cx = None
        self.cy = None
        self.rect = None

    def _degrees(self, radians):
        return (180 * radians) / math.pi

    def _get_transform_cam_to_tag(self, tag):
        tx = tag.x_translation * TAG_SIZE_MM
        ty = tag.y_translation * TAG_SIZE_MM
        tz = tag.z_translation * TAG_SIZE_MM
        rx = tag.x_rotation
        ry = tag.y_rotation
        rz = tag.z_rotation

        rx = normalize(rx)
        ry = normalize(ry)
        rz = normalize(rz)

        # Rotation matrices (intrinsic XYZ: apply Rz first, then Ry, then Rx)
        cos_y, sin_y = math.cos(ry), math.sin(ry)
        cos_z, sin_z = math.cos(rz), math.sin(rz)

        tx_corr = cos_y * (cos_z * tx + sin_z * ty) - sin_y * tz
        tz_corr = sin_y * (cos_z * tx + sin_z * ty) + cos_y * tz

        return {
            "tx": tx_corr,
            "tz": tz_corr,
            "rx": self._degrees(rx),
            "ry": self._degrees(ry),
            "rz": self._degrees(rz),
        }

    def update(self, tag):
        t = self._get_transform_cam_to_tag(tag)

        if self._moveing_avrage is None:
            self._moveing_avrage = {}
            for k in ["tx", "tz", "rx", "ry", "rz"]:
                self._moveing_avrage[k] = t[k]
        else:
            for k in ["tx", "tz", "rx", "ry", "rz"]:
                self._moveing_avrage[k] = self.alpha * t[k] + (1 - self.alpha) * self._moveing_avrage[k]

        self._last_seen = time.ticks_ms()
        self.id = tag.id
        self.tx = self._moveing_avrage["tx"]
        self.tz = self._moveing_avrage["tz"]
        self.rx = self._moveing_avrage["rx"]
        self.ry = self._moveing_avrage["ry"]
        self.rz = self._moveing_avrage["rz"]
        self.cx = tag.cx
        self.cy = tag.cy
        self.rect = tag.rect

    def visible(self):
        if self._last_seen is None:
            return False
        return time.ticks_ms() - self._last_seen < self.timeout_ms

    def reset(self):
        self._moveing_avrage = None
        self._last_seen = None

    def __str__(self):
        if not self.visible:
            return "Tag(not visible)"
        return (
            "Tag(id=%d | tx=%.0f tz=%.0f mm | "
            "yaw=%.1f pitch=%.1f roll=%.1f"
            % (self.id, self.tx, self.tz,
               self.ry, self.rx, self.rz)
        )


# ------------------------------ Localization ------------------------------------------
class Localization:
    def __init__(self, tags):
        self.tags = tags
        self.position = None

    def update(self):
        estimates = []
        weights = []

        for tag_id, info in self.tags.items():
            tag = info["tag"]
            if not tag.visible():
                continue

            dx, dy, dry = cam_to_robot(tag.tx, tag.tz, tag.ry)
            # print("X {:.1f} Z {:.1f} R {:.1f}".format(tag.tx, tag.tz, tag.ry))
            # print(dx, dy, dry)
            # corecting based on heading
            ry = normalize(math.radians(dry))

            h = normalize(math.radians(info["heading"]) + ry)
            cos_h = math.cos(h)
            sin_h = math.sin(h)
            # print(cos_h, sin_h)
            dx_field = cos_h * dx - sin_h * dy
            dy_field = sin_h * dx + cos_h * dy
            # Tag Pose in world
            world_tag_x, world_tag_y = info["pos"]

            robot_x = dx_field + world_tag_x
            robot_y = dy_field + world_tag_y
            estimates.append((robot_x, robot_y))

            dist_from_center = math.sqrt((tag.cx - c_x)**2 + (tag.cy - c_y)**2)
            center_weight = 1.0 / (1.0 + dist_from_center)

            size_weight = tag.rect[2] * tag.rect[3]

            weights.append(center_weight * size_weight)

        if not estimates:
            self.position = None
            return

        total = sum(weights)

        x = 0
        y = 0
        for e, w in zip(estimates, weights):
            x += e[0] * w
            y += e[1] * w
        x /= total
        y /= total

        self.position = (x, y)


def get_tags_with_pose(tags):
    ret_tags = {}
    for key, value in tags.items():
        if isinstance(value, dict) and "pos" in value:
            ret_tags[key] = value
    return ret_tags


class LED_Controll:
    class Color(Enum):
        # Red Green Blue
        OFF =      (False, False, False)
        RED =      (True,  False, False)
        GREEN =    (False, True,  False)
        BLUE =     (False, False, True)
        YELLOW =   (True,  True,  False)
        MEGENTA =  (True,  False, True)
        CYAN =     (False, True,  True)
        WIGHT =    (True,  True,  True)

    def __init__(self):
        self.bits = []

        self.last_time = millis()
        self.toggle_time = 250

        self.bit_index = 0 
        
        self.red_led = LED("LED_RED")
        self.green_led = LED("LED_GREEN")
        self.blue_led = LED("LED_BLUE")

    def _set_color(color: LED_Controll.Color):
        match (color):
            case color.OFF:
                self.red_led.off()
                self.green_led.off()
                self.blue_led.off()
            case color.RED:
                self.red_led.on()
            case color.GREEN:
                self.green_led.on()
            case color.BLUE:
                self.blue_led.on()
            case color.YELLOW:
                self.blue_led.on()
                self.blue_led.on()
            case color.PINK:
                self.blue_led.on()
                self.blue_led.on()
            case color.LIGHT_BLUE:
                self.blue_led.on()
                self.blue_led.on()
            case color.WIGHT:
                self.red_led.on()
                self.green_led.on()
                self.blue_led.on()


    def update(self):
        if (mills() - last_time > toggle_time):
            last_time = mills()
            self._set_color(
                (self.front_bit if self.front_bit else self.Color.OFF) 
                if curently_front_bit 
                else (self.back_bit if self.back_bit else self.Color.OFF))
            
            self.curently_front_bit = not self.curently_front_bit
            
# LED colors needed
# Green - Bin Detected
# Blue - Filed Tag found
# Light Blue - Filed Tag far
# 
# Green and Blue, if both
# Green and light blue if both
    
# ------------------------------ Tags ------------------------------------------
# Tag: {"pos": (X, y), "tag": tag2},
tags = {
    15: {"pos": (0, 304.8), "heading": 0, "tag": Tag()},
    14: {"pos": (152.4, 609.6), "heading": 270, "tag": Tag()},
    13: {"pos": (0, 304.8), "heading": 0, "tag": Tag()},
    12: {"pos": (152.4, 609.6), "heading": 270, "tag": Tag()},
    11: {"pos": (0, 304.8), "heading": 0, "tag": Tag()},
    10: {"pos": (152.4, 609.6), "heading": 270, "tag": Tag()},
    4: {"bin": 1, "tag": Tag()},
}

field_tags = get_tags_with_pose(tags)
loc = Localization(field_tags)

led_controller = LED_Controll()
# ------------------------------ Blob Serch ------------------------------------------
thresholds = (150, 230)
tag_window = [0, int(c_y-(30 * scale)), int(c_x * 2), int(c_y - 5 * scale)]

while True:
    clock.tick()
    img = sensor.snapshot()
    img.rotation_corr(0, 0, 180)

    # box_list = []
    # tag_list = []

    # # Blob Serch
    # for blob in img.find_blobs(
    #         [thresholds],
    #         pixels_threshold=100,
    #         area_threshold=100,
    #         merge=True,
    #         roi=tag_window):
    #     w = min(max(int(blob.w() * 1.2), 10), 160)  # Not too small, not too big.
    #     h = tag_window[3]
    #     x = min(max(int(blob.x() + (blob.w() / 4) - (w * 0.1)), 0), img.width() - 1)
    #     y = tag_window[1]

    #     box_list.append((x, y, w, h))

    #     try:
    #         print(img.find_apriltags(fx=f_x, fy=f_y, cx=c_x, cy=c_y, roi=(x, y, w, h)))
    #         print("no aprial tags found")
    #         # tag_list.extend(img.find_apriltags(fx=f_x, fy=f_y, cx=c_x, cy=c_y, roi=(x, y, w, h)))
    #     except (
    #         MemoryError
    #     ):  # Don't catch all exceptions otherwise you can't stop the script.
    #         print("memory error")
    #         pass

    #     # print(tag_list)

    # for b in box_list:
    #     img.draw_rectangle(b)

    # for tag in tag_list:
    #     img.draw_rectangle(tag.rect)

    try: 
        for tag in img.find_apriltags(fx=f_x, fy=f_y, cx=c_x, cy=c_y, roi=tag_window):
            if tag.id in tags:
                tags[tag.id]["tag"].update(tag)
            if tag.id not in field_tags and in tags:
                led_controller.found_bin_tag()
    except (MemoryError):
        print("memory error")
        pass

    for info in tags.values():
        tag = info["tag"]
        if tag.visible():
            img.draw_rectangle(*tag.rect, color=(255, 0, 0))
            img.draw_cross(tag.cx, tag.cy, color=(0, 255, 0))

            print("X {:.1f} Z {:.1f} R {:.1f}".format(tag.tx, tag.tz, tag.ry))
        else:
            tag.reset()

    # loc.update()
    # if loc.position:
    #     print("X {:.1f}   Y {:.1f}".format(*loc.position))

    led_controller.update()

    img.draw_line(int(c_x), 0, int(c_x), int(c_y * 2))
    img.draw_line(0, int(c_y), int(c_x * 2), int(c_y))

    img.draw_rectangle(*tag_window, color=(255, 255, 255))
