def cardinal_from_bearing(bearing_deg: float) -> str:
    """Map clockwise-from-north degrees to a 4-point cardinal.

    90° sectors; midpoints inclusive toward the clockwise cardinal
    (N 315–45, E 45–135, S 135–225, W 225–315).
    """
    b = bearing_deg % 360
    if 45 <= b < 135:
        return "E"
    if 135 <= b < 225:
        return "S"
    if 225 <= b < 315:
        return "W"
    return "N"


if __name__ == "__main__":
    cases = {
        0: "N",
        90: "E",
        180: "S",
        270: "W",
        45: "E",
        135: "S",
        225: "W",
        315: "N",
        359: "N",
        44.9: "N",
    }
    for deg, want in cases.items():
        got = cardinal_from_bearing(deg)
        assert got == want, f"{deg} -> {got!r}, want {want!r}"
    print("ok")
