# LCD_DotMatrix (Nuke gizmo)

Turns whatever comes into the node into a 48x48 grid of small, clearly
separated round LEDs — the classic red dot-matrix sign / Tamagotchi look,
not a flat pixelated mosaic. By default it's monochrome: each of the 2304
cells samples the source image's brightness and is either a lit red dot
(with a soft glow, like a real LED) or a dim unlit dot, against a black
background, with visible gaps between dots. Works two ways:

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
   small round dot with a soft glow halo (like a real LED) against a
   background colour, sized well inside its cell so neighbouring dots
   don't touch. Defaults to a two-colour "classic LCD" monochrome mode
   (bright red on/dim red off) driven by a luma threshold; full-colour
   mode (each dot keeps the source's own sampled colour) is a toggle away.

Grid Size and Pixels per Dot (exposed on the gizmo) drive both Reformat
nodes and the kernel together, so the render always ends up at
`grid_size * dot_pixel_size` pixels square (480x480 by default: 48 dots at
10px each).

## Controls

| Knob | What it does |
|---|---|
| Grid Size (dots) | Dots across/down. Defaults to 48x48 per spec. |
| Pixels per Dot | Output resolution of each dot cell. |
| Dot Size | Radius of each dot within its cell (0 = pinprick, 0.5 = touching neighbours). Defaults small (0.30) so dots read as separate LEDs, not a solid mosaic. |
| Edge Softness | Anti-aliasing falloff on the dot's hard edge. |
| Glow | Soft halo bleeding outward from each lit dot, like a real LED bloom. |
| Monochrome | On by default — 2-colour on/off LED look. Turn off for each dot to keep the source's own sampled colour. |
| Threshold | Luma cutoff used to decide "on" vs "off" in monochrome mode. |
| Invert | Flips on/off in monochrome mode. |
| On Colour / Off Colour | Lit/unlit dot colours in monochrome mode. Defaults to bright red / dim red for the classic LED-sign look. |
| Background (colour mode) | Background shown around each dot when monochrome is *off*. |

## Install

Copy the `Gizmos/` folder, `init.py`, and `menu.py` into your `~/.nuke`
directory (or any directory on Nuke's plugin path), or point Nuke's
plugin path at this repo. The gizmo will then show up under the
**LCD** toolbar menu, or can be created directly via
`nuke.createNode('LCD_DotMatrix')`.

Requires a Nuke build with BlinkScript (standard in commercial and
non-commercial Nuke). BlinkScript only generates its parameter knobs
(`dotRadius`, `monochrome`, etc.) after the kernel actually compiles,
which doesn't happen automatically just from loading `kernelSource` off
disk — so the gizmo calls `LCD_Kernel['recompile'].execute()` on
creation (`onCreate`) to force it. If the dot controls on the gizmo
still show "Missing knob" (e.g. on a Nuke version where `onCreate`
doesn't fire for gizmo instances), click **Force Recompile** at the top
of the gizmo's panel, then reopen the panel.
