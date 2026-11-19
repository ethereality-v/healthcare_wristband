"""
Man-GO wristband: parametric CAD for the hand pod and the finger sensor holder.

Parts (all print without supports):
  hand_pod_base         holds the ESP32 upside down (header pins up), strap loops for Velcro
  hand_pod_lid          covers the wiring, holds the MMA7361 accelerometer, finger-cable exit
  finger_sensor_holder  holds the GY-MAX30102 against the index-finger pad, Velcro strap slots

How to run:
  pip install build123d
  python wristband_cad.py
Writes STEP and STL files to ./output. Every size is in millimetres and set in the
PARAMETERS section, so measure your parts with calipers and edit the numbers there.

Coordinate system for the pod: X runs along the hand (USB end = wrist side, -X;
finger-cable end = knuckle side, +X), Y runs across the hand, Z points up away from
the skin. The base's bottom face is z = 0.
"""

from pathlib import Path

from build123d import (
    Align, Axis, Box, Color, Compound, Cone, Cylinder, Pos, Rot,
    chamfer, export_step, export_stl, fillet,
)

OUT = Path(__file__).resolve().parent / "output"

# =====================================================================
# PARAMETERS
# =====================================================================

# ---- ESP32 DevKit (30 pin, USB-C, CP2102), mounted upside down -----
ESP_L = 51.0            # board length (measured about 50.8 from the photos)
ESP_W = 27.5            # board width (measured about 27.0 to 27.5)
ESP_T = 1.6             # PCB thickness
ESP_FIT_L = 51.8        # longest board the pocket accepts
ESP_FIT_W = 28.6        # widest board the side fences accept
MODULE_H = 3.1          # ESP32-WROOM-32 module height (it faces the hand)
MODULE_L, MODULE_W = 25.5, 18.0
USB_H = 3.3             # USB-C receptacle height below the board
USB_W = 9.0             # receptacle width
USB_PROTRUDE = 3.2      # how far the receptacle sticks out past the board edge
USB_Y = 0.6             # receptacle offset from the board centre line
BUTTON_Y = 8.3          # EN / BOOT button offset from centre line (both sides)
BUTTON_FROM_USB_EDGE = 2.7
ROW_SPACING = 25.4      # distance between the two header pin rows
PIN_FROM_ANTENNA_END = 5.0   # first pin (EN / D23) from the antenna-end edge
PIN_PITCH = 2.54
PINS_PER_ROW = 15
HEADER_H = 2.5          # black plastic strip under the pins
PIN_LEN = 6.0           # exposed pin above the strip
DUPONT_L = 14.0         # female jumper housing length
DUPONT_W = 2.54

# ---- MMA7361 accelerometer module ----------------------------------
MMA_L = 34.0            # board length (estimated from the photos: please measure)
MMA_W = 17.0            # board width (please measure)
MMA_T = 1.6
MMA_TOP_CLEAR = 2.0     # tallest thing on top of the board (solder tails, chips)
MMA_ROW_INSET = 1.5     # pin row centre from each short end
MMA_PINS = 5            # pins per row

# ---- GY-MAX30102 pulse oximeter -------------------------------------
MAX_L = 14.0            # board size along the finger (please measure)
MAX_W = 14.0            # board size across the finger, along the pin row
MAX_T = 1.6
MAX_CHIP_L, MAX_CHIP_W, MAX_CHIP_H = 5.6, 3.3, 1.55
MAX_PINS = 5

# ---- Hand pod -------------------------------------------------------
WALL = 2.0              # side wall thickness
FLOOR = 2.0             # base floor thickness
UNDER_BOARD = 5.0       # gap between floor and PCB (module, USB-C and buttons live here)
USB_GAP = 0.5           # board edge to inside of the USB end wall
END_SPACE = 10.0        # extra room past the board at the finger end (wires, cable exit)
SIDE_WIRE_SPACE = 7.0   # room beside the jumper housings for wire loops
WIRE_BEND = 5.0         # room under the accelerometer's housings for the wires to bend
CEILING = 2.0           # lid top thickness
RIM_ABOVE_PCB = 2.4     # base wall height above the PCB's top face
CORNER_R = 4.0          # outside corner radius
FIT = 0.25              # sliding clearance between printed parts
SCREW_HOLE = 3.4        # M3 clearance hole in the base
SCREW_PILOT = 2.6       # M3 self-tapping pilot hole in the lid
SCREW_HEAD = 6.4        # M3 flat-head countersink diameter
BOSS_R = 3.0
FILAMENT_HOLE = 2.0     # holes for 1.75 mm filament pins that hold the accelerometer
STRAP_OPENING = 32.0    # Velcro strap loops: length along the pod (fits up to ~30 mm straps)
STRAP_GAP = 3.2         # gap the strap passes through
STRAP_BAR = 2.2         # loop bar thickness
STRAP_BAR_H = 5.0       # loop height

# ---- Finger sensor holder -------------------------------------------
FH_LEN = 24.0           # along the finger
FH_WIDTH = 31.0         # across the finger, including strap wings
FH_THICK = 7.5          # at the wings
FINGER_R = 13.0         # radius of the finger-pad cradle
CRADLE_W = 19.0         # width of the curved cradle
FH_STRAP_W = 14.0       # finger strap slot length (fits straps up to ~13 mm)
FH_STRAP_GAP = 2.8
CHIP_PROUD = 0.9        # how far the sensor chip sits above the cradle surface

# =====================================================================
# DERIVED POSITIONS (no need to edit)
# =====================================================================
L_IN = USB_GAP + ESP_FIT_L + END_SPACE
W_IN = 2 * (ROW_SPACING / 2 + DUPONT_W / 2 + SIDE_WIRE_SPACE)
L_OUT = L_IN + 2 * WALL
W_OUT = W_IN + 2 * WALL

Z_PCB_BOT = FLOOR + UNDER_BOARD
Z_PCB_TOP = Z_PCB_BOT + ESP_T
Z_HEADER_TOP = Z_PCB_TOP + HEADER_H
Z_DUPONT_TOP = Z_HEADER_TOP + DUPONT_L
Z_RIM = Z_PCB_TOP + RIM_ABOVE_PCB                    # base/lid split plane
Z_MMA_HOUSING_BOT = Z_PCB_TOP + WIRE_BEND
Z_MMA_BOT = Z_MMA_HOUSING_BOT + DUPONT_L + HEADER_H
Z_MMA_TOP = Z_MMA_BOT + MMA_T
Z_CEIL = Z_MMA_TOP + MMA_TOP_CLEAR + 0.6
Z_TOP = Z_CEIL + CEILING

X_USB_WALL = -L_IN / 2                              # inside face of the USB end wall
X_EDGE = X_USB_WALL + USB_GAP                       # board edge at the USB end
X_BOARD = X_EDGE + ESP_L / 2                        # board centre
X_ANT = X_EDGE + ESP_L                              # board edge at the antenna end
X_MMA = X_BOARD                                     # accelerometer sits over the board centre
CORNERS = [(sx * (L_IN / 2 - BOSS_R + 0.6), sy * (W_IN / 2 - BOSS_R + 0.6)) for sx in (-1, 1) for sy in (-1, 1)]


def box(lx, ly, lz, x=0.0, y=0.0, z=0.0):
    """Box centred on (x, y) in plan, sitting on height z."""
    return Pos(x, y, z) * Box(lx, ly, lz, align=(Align.CENTER, Align.CENTER, Align.MIN))


def box_span(x0, x1, y0, y1, z0, z1):
    """Box from corner ranges."""
    return box(x1 - x0, y1 - y0, z1 - z0, (x0 + x1) / 2, (y0 + y1) / 2, z0)


def cyl(r, h, x=0.0, y=0.0, z=0.0):
    return Pos(x, y, z) * Cylinder(r, h, align=(Align.CENTER, Align.CENTER, Align.MIN))


def pin_xs():
    """X positions of the 15 header pins, antenna end first."""
    return [X_ANT - PIN_FROM_ANTENNA_END - k * PIN_PITCH for k in range(PINS_PER_ROW)]


# =====================================================================
# HAND POD BASE
# =====================================================================
def make_base():
    outer = box(L_OUT, W_OUT, Z_RIM)
    outer = fillet(outer.edges().filter_by(Axis.Z), CORNER_R)
    outer = chamfer(outer.edges().group_by(Axis.Z)[0], 0.8)          # soft bottom edge
    cavity = box(L_IN, W_IN, Z_RIM, z=FLOOR)
    cavity = fillet(cavity.edges().filter_by(Axis.Z), CORNER_R - WALL)
    base = outer - cavity

    # Corner columns for the four M3 screws (screwed in from underneath).
    for x, y in CORNERS:
        base += cyl(BOSS_R, Z_RIM - FLOOR, x, y, FLOOR)
        base -= cyl(SCREW_HOLE / 2, Z_RIM + 1, x, y, -0.5)
        base -= Pos(x, y, 0) * Cone(SCREW_HEAD / 2, SCREW_HOLE / 2, (SCREW_HEAD - SCREW_HOLE) / 2,
                                     align=(Align.CENTER, Align.CENTER, Align.MIN))

    # Pad under the ESP32 module: the board rests on the module's metal can here.
    can_x = X_ANT - 14.0
    base += box(12.0, 12.0, Z_PCB_BOT - MODULE_H - FLOOR, can_x, 0, FLOOR)

    # Side fences locate the board edges (stay below the PCB top so the header strips clear).
    fence_y = ESP_FIT_W / 2
    for s in (-1, 1):
        y0, y1 = sorted((s * fence_y, s * (fence_y + 1.2)))
        base += box_span(X_EDGE + 9.0, X_ANT - 8.0, y0, y1, FLOOR, Z_PCB_TOP - 0.3)

    # Antenna-end stops with lips: slide this end of the board under the lips first.
    stop_x = X_EDGE + ESP_FIT_L
    for yc in (-6.0, 6.0):
        base += box_span(stop_x, stop_x + 1.6, yc - 3.0, yc + 3.0, FLOOR, Z_PCB_TOP + 1.1)
        base += box_span(stop_x - 2.0, stop_x, yc - 3.0, yc + 3.0, Z_PCB_TOP + 0.1, Z_PCB_TOP + 1.1)

    # USB-C: open-topped slot so the receptacle drops in; the lid's tab closes it from above.
    usb_z0 = Z_PCB_BOT - USB_H - 0.05
    wall_x0, wall_x1 = -L_OUT / 2 - 1, X_USB_WALL + 0.01
    base -= box_span(wall_x0, wall_x1, USB_Y - 5.1, USB_Y + 5.1, usb_z0, Z_RIM + 1)
    # Recess on the outside so a cable's moulded plug can seat fully.
    base -= box_span(wall_x0, -L_OUT / 2 + 1.0, USB_Y - 6.75, USB_Y + 6.75, 1.4, Z_RIM + 1)

    # Holes under the EN and BOOT buttons (press with a paperclip when the pod is off the hand).
    for s in (-1, 1):
        base -= cyl(2.25, FLOOR + 2, X_EDGE + BUTTON_FROM_USB_EDGE, s * BUTTON_Y, -1)

    # Velcro strap loops on both long sides.
    for s in (-1, 1):
        y_wall = s * W_OUT / 2
        y_bar0 = y_wall + s * STRAP_GAP
        y_bar1 = y_bar0 + s * STRAP_BAR
        ya, yb = sorted((y_wall - s * 1.0, y_bar1))
        for xe in (-STRAP_OPENING / 2 - 3.0, STRAP_OPENING / 2):
            base += box_span(xe, xe + 3.0, ya, yb, 0, STRAP_BAR_H)
        y0, y1 = sorted((y_bar0, y_bar1))
        base += box_span(-STRAP_OPENING / 2 - 3.0, STRAP_OPENING / 2 + 3.0, y0, y1, 0, STRAP_BAR_H)
    return base


# =====================================================================
# HAND POD LID
# =====================================================================
def make_lid():
    h = Z_TOP - Z_RIM
    outer = box(L_OUT, W_OUT, h, z=Z_RIM)
    outer = fillet(outer.edges().filter_by(Axis.Z), CORNER_R)
    outer = fillet(outer.edges().group_by(Axis.Z)[-1], 2.5)           # rounded top edges
    inner = box(L_IN, W_IN, Z_CEIL - Z_RIM, z=Z_RIM - 0.01)
    inner = fillet(inner.edges().filter_by(Axis.Z), CORNER_R - WALL)
    lid = outer - inner

    # Screw bosses (M3 self-tapping, screwed from underneath through the base).
    for x, y in CORNERS:
        lid += cyl(BOSS_R, 10.0, x, y, Z_RIM)
        lid -= cyl(SCREW_PILOT / 2, 10.5, x, y, Z_RIM - 0.5)

    # Alignment skirt that drops inside the base walls.
    t = 1.2
    xs0, xs1 = -L_IN / 2 + 2 * BOSS_R + 0.5, L_IN / 2 - 2 * BOSS_R - 0.5
    for s in (-1, 1):
        y0, y1 = sorted((s * (W_IN / 2 - FIT), s * (W_IN / 2 - FIT - t)))
        lid += box_span(xs0, xs1, y0, y1, Z_RIM - 2.5, Z_RIM + 2.0)
        ya, yb = sorted((s * (W_IN / 2 - FIT - t), s * (W_IN / 2 + 0.5)))
        lid += box_span(xs0, xs1, ya, yb, Z_RIM, Z_RIM + 2.0)
    lid += box_span(L_IN / 2 - FIT - t, L_IN / 2 + 0.5, -12, 12, Z_RIM, Z_RIM + 2.0)
    lid += box_span(L_IN / 2 - FIT - t, L_IN / 2 - FIT, -12, 12, Z_RIM - 2.5, Z_RIM + 0.01)

    # USB end: skirt presses the board edge down, tab fills the open USB slot above the receptacle.
    lid += box_span(X_USB_WALL + FIT, X_USB_WALL + FIT + t, -10, 10, Z_PCB_TOP + 0.1, Z_RIM + 0.01)
    lid += box_span(X_USB_WALL - 0.5, X_USB_WALL + FIT + t, -10, 10, Z_RIM, Z_RIM + 2.0)
    lid += box_span(-L_OUT / 2, X_USB_WALL + 0.01, USB_Y - 5.1 + 0.15, USB_Y + 5.1 - 0.15,
                    Z_PCB_BOT + 0.15, Z_RIM + 0.01)
    lid += box_span(-L_OUT / 2, -L_OUT / 2 + 1.0, USB_Y - 6.75 + 0.15, USB_Y + 6.75 - 0.15,
                    Z_PCB_BOT + 2.2, Z_RIM + 0.01)

    # Accelerometer frame hanging from the ceiling.
    fl, fw, fwall = MMA_L + 0.6, MMA_W + 0.6, 1.3
    z_fbot = Z_MMA_BOT - 2.6
    frame = box(fl + 2 * fwall, fw + 2 * fwall, Z_CEIL - z_fbot + 0.01, X_MMA, 0, z_fbot)
    frame -= box(fl, fw, Z_CEIL - z_fbot + 1, X_MMA, 0, z_fbot - 0.5)
    # Stop ribs keep the board from rising toward the ceiling.
    for s in (-1, 1):
        y0, y1 = sorted((s * (fw / 2 + 0.3), s * (fw / 2 - 0.8)))
        frame += box_span(X_MMA - 4, X_MMA + 4, y0, y1, Z_MMA_TOP + 0.15, Z_CEIL + 0.01)
    # Holes for two 1.75 mm filament pins that pass under the board and hold it up.
    z_pin = Z_MMA_BOT - 0.15 - 1.75 / 2
    for dx in (-6.0, 6.0):
        frame -= Pos(X_MMA + dx, 0, z_pin) * Rot(X=90) * Cylinder(FILAMENT_HOLE / 2, fw + 2 * fwall + 2)
    lid += frame

    # Finger-cable exit (4 wires) with zip-tie holes for strain relief.
    zc, slot_w, slot_h = 18.0, 10.0, 6.0
    xw0, xw1 = L_IN / 2 - 1, L_OUT / 2 + 1
    lid -= box_span(xw0, xw1, -slot_w / 2 + slot_h / 2, slot_w / 2 - slot_h / 2, zc - slot_h / 2, zc + slot_h / 2)
    for yc in (-slot_w / 2 + slot_h / 2, slot_w / 2 - slot_h / 2):
        lid -= Pos((xw0 + xw1) / 2, yc, zc) * Rot(Y=90) * Cylinder(slot_h / 2, xw1 - xw0)
    for yc in (-8.5, 8.5):
        lid -= Pos((xw0 + xw1) / 2, yc, zc) * Rot(Y=90) * Cylinder(1.2, xw1 - xw0)
    return lid


# =====================================================================
# FINGER SENSOR HOLDER (local frame: Z up = toward the finger, X along the finger,
# -X = toward the hand where the pins and wires leave)
# =====================================================================
def make_finger_holder():
    body = box(FH_LEN, FH_WIDTH, FH_THICK)
    body = fillet(body.edges().filter_by(Axis.Z), 3.0)
    # Curved cradle for the finger pad.
    half = CRADLE_W / 2
    sag = FINGER_R - (FINGER_R ** 2 - half ** 2) ** 0.5
    zc = FH_THICK - sag + FINGER_R
    body -= Pos(0, 0, zc) * Rot(Y=90) * Cylinder(FINGER_R, FH_LEN + 2)
    z_surface = zc - FINGER_R                                     # cradle bottom (centre line)

    # Board pocket, open toward the finger. The board rests on ledges on three sides.
    z_board_top = z_surface + CHIP_PROUD - MAX_CHIP_H
    z_board_bot = z_board_top - MAX_T
    pl, pw = MAX_L + 0.4, MAX_W + 0.4
    body -= box(pl, pw, FH_THICK, 0, 0, z_board_bot)
    body -= box(pl - 2.4, pw - 2.4, FH_THICK, 0.3, 0, -1)            # opening under the board
    body -= box_span(-pl / 2 - 0.01, -pl / 2 + 3.4, -pw / 2 + 0.4, pw / 2 - 0.4, -1, z_board_bot + 0.01)  # header slot
    # Small snap bumps that hold the board in the pocket.
    for s in (-1, 1):
        y0, y1 = sorted((s * pw / 2, s * (pw / 2 - 0.35)))
        body += box_span(-2.0, 2.0, y0, y1, z_board_top + 0.05, z_board_top + 0.65)

    # Strap slots in the wings.
    for s in (-1, 1):
        body -= box(FH_STRAP_W, FH_STRAP_GAP, FH_THICK + 2, 1.0, s * (FH_WIDTH / 2 - 3.6), -1)

    return body, z_board_bot, z_board_top


# =====================================================================
# STAND-IN PARTS (for checking fit and for pictures, not for printing)
# =====================================================================
def make_esp32():
    parts = {}
    parts["pcb"] = box(ESP_L, ESP_W, ESP_T, X_BOARD, 0, Z_PCB_BOT)
    parts["module"] = box(MODULE_L, MODULE_W, MODULE_H, X_ANT - 0.3 - MODULE_L / 2, 0, Z_PCB_BOT - MODULE_H)
    parts["usb"] = box(7.35, USB_W, USB_H, X_EDGE - USB_PROTRUDE + 7.35 / 2, USB_Y, Z_PCB_BOT - USB_H)
    btn = None
    for s in (-1, 1):
        b = box(4.0, 3.0, 2.5, X_EDGE + BUTTON_FROM_USB_EDGE, s * BUTTON_Y, Z_PCB_BOT - 2.5)
        btn = b if btn is None else btn + b
    parts["buttons"] = btn
    xs = pin_xs()
    x_mid = (xs[0] + xs[-1]) / 2
    hdr = pins = dup = None
    for s in (-1, 1):
        y = s * ROW_SPACING / 2
        h = box(PINS_PER_ROW * PIN_PITCH, PIN_PITCH, HEADER_H, x_mid, y, Z_PCB_TOP)
        hdr = h if hdr is None else hdr + h
        for x in xs:
            p = box(0.64, 0.64, PIN_LEN, x, y, Z_HEADER_TOP)
            d = box(DUPONT_W, DUPONT_W, DUPONT_L, x, y, Z_HEADER_TOP)
            pins = p if pins is None else pins + p
            dup = d if dup is None else dup + d
    parts["headers"] = hdr
    parts["housings"] = dup          # worst case: a jumper on every pin
    return parts


def make_mma():
    parts = {}
    parts["pcb"] = box(MMA_L, MMA_W, MMA_T, X_MMA, 0, Z_MMA_BOT)
    parts["top_parts"] = box(MMA_L - 9, MMA_W - 5, 1.5, X_MMA, 0, Z_MMA_TOP)
    rows = None
    for s in (-1, 1):
        x = X_MMA + s * (MMA_L / 2 - MMA_ROW_INSET)
        tails = box(PIN_PITCH, MMA_PINS * PIN_PITCH, MMA_TOP_CLEAR, x, 0, Z_MMA_TOP)
        strip = box(PIN_PITCH, MMA_PINS * PIN_PITCH, HEADER_H, x, 0, Z_MMA_BOT - HEADER_H)
        housing = box(DUPONT_W, MMA_PINS * DUPONT_W, DUPONT_L, x, 0, Z_MMA_HOUSING_BOT)
        r = tails + strip + housing
        rows = r if rows is None else rows + r
    parts["headers"] = rows
    pins = None
    fw = MMA_W + 0.6 + 2 * 1.3
    for dx in (-6.0, 6.0):
        p = Pos(X_MMA + dx, 0, Z_MMA_BOT - 0.15 - 1.75 / 2) * Rot(X=90) * Cylinder(1.75 / 2, fw + 0.6)
        pins = p if pins is None else pins + p
    parts["filament_pins"] = pins
    return parts


def make_max(z_board_bot, z_board_top):
    parts = {}
    parts["pcb"] = box(MAX_L, MAX_W, MAX_T, 0, 0, z_board_bot)
    parts["chip"] = box(MAX_CHIP_L, MAX_CHIP_W, MAX_CHIP_H, 0.5, 0, z_board_top)
    x_row = -MAX_L / 2 + 1.5
    strip = box(PIN_PITCH, MAX_PINS * PIN_PITCH, HEADER_H, x_row, 0, z_board_bot - HEADER_H)
    housing = box(DUPONT_W, MAX_PINS * DUPONT_W, DUPONT_L, x_row, 0, z_board_bot - HEADER_H - DUPONT_L)
    parts["header"] = strip + housing
    return parts


def build_all():
    base = make_base()
    lid = make_lid()
    holder, zb0, zb1 = make_finger_holder()
    return base, lid, holder, make_esp32(), make_mma(), make_max(zb0, zb1)


def summary():
    return {
        "pod outside (L x W x H)": f"{L_OUT:.1f} x {W_OUT:.1f} x {Z_TOP:.1f} mm",
        "pod with strap loops (W)": f"{W_OUT + 2 * (STRAP_GAP + STRAP_BAR):.1f} mm",
        "interior (L x W)": f"{L_IN:.1f} x {W_IN:.1f} mm",
        "ESP32 PCB bottom / top": f"z = {Z_PCB_BOT:.1f} / {Z_PCB_TOP:.1f}",
        "jumper housing tops on ESP32": f"z = {Z_DUPONT_TOP:.1f}",
        "accelerometer board bottom / top": f"z = {Z_MMA_BOT:.1f} / {Z_MMA_TOP:.1f}",
        "accelerometer above ESP32 PCB": f"{Z_MMA_BOT - Z_PCB_TOP:.1f} mm",
        "base / lid split": f"z = {Z_RIM:.1f}",
        "finger holder (L x W x T)": f"{FH_LEN:.1f} x {FH_WIDTH:.1f} x {FH_THICK:.1f} mm",
    }


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    base, lid, holder, esp, mma, mx = build_all()

    # Print-ready parts, placed in their printing orientation.
    lid_print = Pos(0, 0, Z_TOP) * Rot(X=180) * lid           # upside down: ceiling on the bed
    for name, part in (("hand_pod_base", base), ("hand_pod_lid", lid_print), ("finger_sensor_holder", holder)):
        export_step(part, str(OUT / f"{name}.step"))
        export_stl(part, str(OUT / f"{name}.stl"), tolerance=0.02, angular_tolerance=0.15)

    # Assembly with stand-in electronics (for viewing in CAD software).
    def tag(shape, label, color):
        shape.label = label
        shape.color = Color(color)
        return shape

    fh_place = Pos(L_OUT / 2 + 45, 0, 0)
    children = [
        tag(base, "hand_pod_base", "#5AC31A"),
        tag(lid, "hand_pod_lid", "#FFA41B"),
        tag(fh_place * holder, "finger_sensor_holder", "#A560E8"),
    ]
    colors = {"pcb": "#1F2A44", "module": "#B8B8B8", "usb": "#C0C0C0", "buttons": "#EEEEEE",
              "headers": "#202020", "housings": "#202020", "top_parts": "#333333",
              "filament_pins": "#FF4B6E", "chip": "#3A3A3A", "header": "#202020"}
    for group, parts, place in (("esp32", esp, Pos()), ("mma7361", mma, Pos()), ("max30102", mx, fh_place)):
        for key, shape in parts.items():
            children.append(tag(place * shape, f"{group}_{key}", colors.get(key, "#444444")))
    export_step(Compound(children=children, label="manGO_wristband_assembly"), str(OUT / "assembly.step"))

    for k, v in summary().items():
        print(f"{k:34s} {v}")
    print("Wrote", ", ".join(sorted(p.name for p in OUT.iterdir())))
