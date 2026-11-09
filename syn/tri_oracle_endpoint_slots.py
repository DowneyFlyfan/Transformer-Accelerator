"""Integer-grid placement of equal-width cells in measured empty row intervals.

This supplies coordinates only. Native placement, routing and timing checks
remain mandatory; rectangle containment alone does not prove physical legality.
"""
from bisect import bisect_left, bisect_right


def _geometry(gaps, width, site, origin, height):
    if any(type(value) is not int for value in (width, site, origin, height)):
        raise ValueError("Grid dimensions must be integers")
    if min(width, site, height) <= 0 or width % site:
        raise ValueError("Positive cell width must occupy whole sites")
    rows = {}
    for left, right, y, orient in gaps:
        if (any(type(value) is not int for value in (left, right, y)) or
                left >= right or orient not in ("N", "FS") or
                (left - origin) % site or (right - origin) % site):
            raise ValueError("Invalid row interval or site alignment")
        row = rows.setdefault(y, {"orient": orient, "gaps": []})
        if row["orient"] != orient:
            raise ValueError("Conflicting orientation in one row")
        row["gaps"].append((left, right))
    if not rows:
        raise ValueError("No measured row intervals")
    ys = sorted(rows)
    if any(b - a < height for a, b in zip(ys, ys[1:])):
        raise ValueError("Row rectangles overlap")
    for row in rows.values():
        row["gaps"].sort()
        if any(b[0] < a[1] for a, b in zip(row["gaps"], row["gaps"][1:])):
            raise ValueError("Free intervals overlap")
    return rows


def assign_slots(gaps, targets, *, width, site, origin, height):
    """Reserve nearest Manhattan-distance slots, in supplied target priority.

    Ties choose lower row then lower x. Only the two intervals bracketing x
    can be nearest in a row. Rows farther than the current best total distance
    cannot improve it, so the search stops without scanning the whole chip.
    """
    rows = _geometry(gaps, width, site, origin, height)
    for row in rows.values():
        row["gaps"] = [(a, b) for a, b in row["gaps"] if b - a >= width]
        row["starts"] = [a for a, _ in row["gaps"]]
    ys = sorted(rows)
    slots = {}
    for name, target_x, target_y in targets:
        if (not isinstance(name, str) or not name or any(c.isspace() for c in name) or
                name in slots or type(target_x) is not int or type(target_y) is not int):
            raise ValueError("Invalid or duplicate placement target")
        upper = bisect_left(ys, target_y)
        lower = upper - 1
        best = None
        while lower >= 0 or upper < len(ys):
            below = (abs(ys[lower] - target_y), ys[lower]) if lower >= 0 else None
            above = (abs(ys[upper] - target_y), ys[upper]) if upper < len(ys) else None
            if above is None or (below is not None and below <= above):
                distance_y, y = below
                lower -= 1
            else:
                distance_y, y = above
                upper += 1
            if best is not None and distance_y > best[0]:
                break
            row = rows[y]
            index = bisect_right(row["starts"], target_x)
            for candidate in (index - 1, index):
                if not 0 <= candidate < len(row["gaps"]):
                    continue
                left, right = row["gaps"][candidate]
                floor = origin + ((target_x - origin) // site) * site
                for grid_x in (floor, floor + site):
                    x = min(max(grid_x, left), right - width)
                    choice = (abs(x - target_x) + distance_y, y, x, candidate)
                    if best is None or choice < best:
                        best = choice
        if best is None:
            raise ValueError("Measured free slots are exhausted")
        _, y, x, index = best
        row = rows[y]
        left, right = row["gaps"][index]
        replacements = [(a, b) for a, b in ((left, x), (x + width, right)) if b - a >= width]
        row["gaps"][index:index + 1] = replacements
        row["starts"][index:index + 1] = [a for a, _ in replacements]
        slots[name] = (x, y, row["orient"])
    return slots


def verify_slots(gaps, slots, target_names, *, width, site, origin, height):
    """Independently check coverage, original-gap containment and new overlaps."""
    rows = _geometry(gaps, width, site, origin, height)
    names = list(target_names)
    if len(names) != len(set(names)) or set(slots) != set(names):
        raise ValueError("Placement target coverage differs")
    placed = {}
    for name, (x, y, orient) in slots.items():
        if (type(x) is not int or type(y) is not int or y not in rows or
                (x - origin) % site or orient != rows[y]["orient"]):
            raise ValueError("Placement is off grid or has the wrong row/orientation")
        if not any(left <= x and x + width <= right for left, right in rows[y]["gaps"]):
            raise ValueError("Placement is outside an original free interval")
        placed.setdefault(y, []).append(x)
    for xs in placed.values():
        xs.sort()
        if any(right < left + width for left, right in zip(xs, xs[1:])):
            raise ValueError("New cell rectangles overlap")
