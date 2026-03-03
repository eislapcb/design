"""
Eisla — Reference Designator Assignment (python/refdes.py)

Shared by schematic.py, netlist.py, and placement.py so that all pipeline
stages produce identical, deterministic ref designators from the same
resolved component list.
"""

PREFIX_FALLBACK = {
    "mcu": "U", "power": "U", "sensor": "U", "comms": "U",
    "motor_driver": "U", "display": "LCD", "connector": "J",
    "passive": "?",
}

SUB_PREFIX = {
    "capacitor": "C", "resistor": "R", "diode": "D", "diode_flyback": "D",
    "led": "LED", "mosfet_n": "Q", "mosfet_p": "Q", "tvs_esd": "D",
    "tvs_diode": "D", "crystal": "X", "inductor": "L", "fuse": "F",
    "test_point": "TP", "fiducial": "FID",
}


def assign_refs(resolved_components, db):
    """
    Assign unique reference designators to each resolved component instance.

    Args:
        resolved_components: list from resolved.json["resolved_components"]
        db: components.json dict (component_id -> component data)

    Returns:
        list of component dicts with 'ref' field added.
    """
    counters = {}
    result = []

    for rc in resolved_components:
        comp = db.get(rc["component_id"], {})
        prefix = (
            comp.get("ref_designator_prefix")
            or SUB_PREFIX.get(comp.get("subcategory", ""))
            or PREFIX_FALLBACK.get(comp.get("category", ""), "U")
        )
        n = counters.get(prefix, 0) + 1
        counters[prefix] = n
        result.append({**rc, "ref": f"{prefix}{n}"})

    return result
