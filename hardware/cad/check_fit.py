"""
Fit check for the wristband CAD: every printed part against every stand-in component,
and the base against the lid. Run after changing parameters in wristband_cad.py:

    python check_fit.py

Prints the overlap volume for each pair (should be 0) and "problems: 0" when everything fits.
"""

import wristband_cad as W

base, lid, holder, esp, mma, mx = W.build_all()


def overlap(a, b):
    return (a & b).volume


print("== printed parts")
for name, part in (("base", base), ("lid", lid), ("finger holder", holder)):
    print(f"  {name:14s} valid={part.is_valid}  pieces={len(part.solids())}  volume={part.volume / 1000:5.1f} cm3")

problems = 0
print("== collisions (mm3, should be 0)")
pairs = [(p, part, g, k, c) for p, part in (("base", base), ("lid", lid))
         for g, parts in (("esp32", esp), ("mma7361", mma)) for k, c in parts.items()]
pairs += [("holder", holder, "max30102", k, c) for k, c in mx.items()]
for pname, part, group, key, comp in pairs:
    v = overlap(part, comp)
    flag = "" if v < 0.01 else "   <-- collision"
    problems += bool(flag)
    print(f"  {pname:6s} x {group}.{key:14s} {v:8.3f}{flag}")

v = overlap(base, lid)
problems += v >= 0.01
print(f"  base   x lid {v:31.3f}" + ("" if v < 0.01 else "   <-- collision"))

for k1, c1 in mma.items():
    for k2, c2 in esp.items():
        v = overlap(c1, c2)
        if v >= 0.01:
            problems += 1
            print(f"  accelerometer.{k1} x esp32.{k2} {v:.2f}   <-- collision")

inner = W.box(W.L_IN, W.W_IN, W.Z_CEIL - W.FLOOR, z=W.FLOOR)
occupied = base + lid
for parts in (esp, mma):
    for comp in parts.values():
        occupied = occupied + comp
print(f"== free space inside the closed pod for wire loops: {(inner - occupied).volume / 1000:.1f} cm3")
print("problems:", problems)
