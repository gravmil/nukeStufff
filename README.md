# LCD_DotMatrix (Nuke gizmo)

Turns whatever comes into the node into a 48x48 grid of small, clearly
separated round dots — the dot-matrix display / Tamagotchi look, not a
flat pixelated mosaic. By default each of the 2304 cells samples the
source image and renders as a solid, flat-filled dot in that cell's own
colour, with visible gaps between dots. A monochrome toggle gives the
classic 2-colour LED-sign look (e.g. red on black) if you want it. Works
two ways:

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
| Dot Size | Radius of each dot within its cell (0 = pinprick, 0.5 = touching neighbours). Defaults small (0.30) so dots read as separate dots, not a solid mosaic. |
| Edge Softness | Anti-aliasing falloff on the dot's hard edge. Defaults low so each dot is a crisp, solid fill. |
| Glow | Soft halo bleeding outward from each dot, like an LED bloom. Off (0) by default. |
| Monochrome | Off by default (each dot keeps the source's own sampled colour). Turn on for the 2-colour on/off LED-sign look. |
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

---

# Remap_Range (Nuke gizmo)

A simple range-remap node: takes an input range `[Old Min, Old Max]` and
maps it onto an output range `[New Min, New Max]`, then applies an overall
`Multiply` (gain). Built from a plain Expression node — no BlinkScript, so
it loads and works everywhere Nuke does.

Per channel, the math is:

```
normalized = (in - Old Min) / (Old Max - Old Min)
out        = (normalized * (New Max - New Min) + New Min) * Multiply
```

If `Old Max == Old Min` the normalized term falls back to 0 (no
divide-by-zero blowup).

## Controls

| Knob | What it does |
|---|---|
| Multiply | Overall gain applied to the remapped result. Default 1. |
| Old Min / Old Max | The input range being remapped *from*. Default 0 / 1. |
| New Min / New Max | The output range being remapped *to*. Default 0 / 1. |
| Include alpha | Also remap alpha. Off = alpha passes through untouched. |
| Clamp to New range | Clamp the output into `[New Min, New Max]`. Off by default. |

With the defaults (Old 0..1 → New 0..1, Multiply 1) it's a pass-through;
change the ranges to do the actual remap. RGB are always remapped; alpha
only when **Include alpha** is on.

Create it from the **Custom** toolbar menu, or via
`nuke.createNode('Remap_Range')`.
