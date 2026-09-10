def cardinal_from_bearing(bearing_deg: float) -> str:
    """Map clockwise-from-north degrees to a 4-point cardinal.

    90° sectors; midpoints inclusive toward the clockwise cardinal
    (North 315–45, East 45–135, South 135–225, West 225–315).
    """
    b = bearing_deg % 360
    if 45 <= b < 135:
        return "East"
    if 135 <= b < 225:
        return "South"
    if 225 <= b < 315:
        return "West"
    return "North"


if __name__ == "__main__":
    cases = {
        0: "North",
        90: "East",
        180: "South",
        270: "West",
        45: "East",
        135: "South",
        225: "West",
        315: "North",
        359: "North",
        44.9: "North",
    }
    for deg, want in cases.items():
        got = cardinal_from_bearing(deg)
        assert got == want, f"{deg} -> {got!r}, want {want!r}"
    print("ok")
