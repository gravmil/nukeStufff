# LCD_DotMatrix (Nuke gizmo)

Turns whatever comes into the node into a 48x48 grid of round dots, like a
segmented LCD / dot-matrix display. Works two ways:

- **Image input**: connect any Read/upstream node into it as normal.
- **Paint input**: leave it unconnected (or connect nothing you care about)
  and click **Open Paint Panel** on the gizmo to paint directly on the
  built-in RotoPaint node inside it — your strokes get quantized into dots
  the same way an image would.

You can also do both at once: feed it an image and paint on top of it in
the internal Paint node before it gets pixelated down to the grid.

## How it works

The gizmo (`Gizmos/LCD_DotMatrix.gizmo`) is a `Group` containing:

1. `Paint` — a `RotoPaint` node (passthrough until you draw on it) so the
   tool doubles as a paint-to-LCD tool with no external image required.
2. `Pixelate` — a `Reformat` that box/area-filters the image down to a
   48x48 grid (one averaged colour per dot cell).
3. `Upscale` — a `Reformat` that blows the 48x48 grid back up to a working
   resolution with nearest-neighbour sampling (no new detail, just bigger
   flat blocks — one per cell).
4. `LCD_Kernel` — a `BlinkScript` node that turns each flat block into a
   round (or soft-edged) dot against a background colour, optionally in a
   two-colour "classic LCD" monochrome mode driven by a luma threshold.

Grid Size and Pixels per Dot (exposed on the gizmo) drive both Reformat
nodes and the kernel together, so the render always ends up at
`grid_size * dot_pixel_size` pixels square (480x480 by default: 48 dots at
10px each).

## Controls

| Knob | What it does |
|---|---|
| Grid Size (dots) | Dots across/down. Defaults to 48x48 per spec. |
| Pixels per Dot | Output resolution of each dot cell. |
| Dot Size | Radius of each dot within its cell (0 = pinprick, 0.5 = touching neighbours). |
| Edge Softness | Anti-aliasing falloff on the dot edge. |
| Monochrome | Switches to a 2-colour on/off LCD look. |
| Threshold | Luma cutoff used to decide "on" vs "off" in monochrome mode. |
| Invert | Flips on/off in monochrome mode. |
| On Colour / Off Colour | Colours used in monochrome mode. |
| Background (colour mode) | Background shown around each dot when *not* in monochrome mode. |

## Install

Copy the `Gizmos/` folder, `init.py`, and `menu.py` into your `~/.nuke`
directory (or any directory on Nuke's plugin path), or point Nuke's
plugin path at this repo. The gizmo will then show up under the
**LCD** toolbar menu, or can be created directly via
`nuke.createNode('LCD_DotMatrix')`.

Requires a Nuke build with BlinkScript (standard in commercial and
non-commercial Nuke). The first time you open the gizmo, select the
internal `LCD_Kernel` node and hit **Recompile** if the dot pattern
doesn't render immediately — Nuke sometimes needs one manual recompile
the first time a hand-authored `.gizmo` with a Blink kernel loads.

This was authored and hand-verified against standard Nuke `.gizmo` /
BlinkScript syntax without a live Nuke instance to test-compile in this
environment — if any knob name differs slightly across Nuke versions,
open the gizmo (`Edit > Node > Open` on the underlying group) and check
the `Pixelate`/`Upscale` Reformat nodes' `format` knob and the
`LCD_Kernel` BlinkScript node's parameters against the table above.
