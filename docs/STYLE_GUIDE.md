# Wire Aesthetic Style Guide

> The wireframe/vector look is a **deliberate art direction**, not a shortcut.
> Think Battlezone, DEFCON, Alien's ship computers, submarine sonar displays.
> Every visual choice should feel like a purpose-built military/scientific instrument.

## Colour Palette

### CSS Custom Properties

```css
:root {
  /* ===== Base backgrounds ===== */
  --bg-primary: #0a0a0a;
  --bg-secondary: #111111;
  --bg-panel: #0d0d0d;
  --bg-panel-header: #151515;
  
  /* ===== Alert level colours ===== */
  /* The primary UI colour shifts based on alert level. */
  /* Default (green) is used in lobby and normal operations. */
  --alert-green: #00ff41;
  --alert-green-dim: rgba(0, 255, 65, 0.3);
  --alert-green-glow: rgba(0, 255, 65, 0.15);
  
  --alert-yellow: #ffb000;
  --alert-yellow-dim: rgba(255, 176, 0, 0.3);
  --alert-yellow-glow: rgba(255, 176, 0, 0.15);
  
  --alert-red: #ff2020;
  --alert-red-dim: rgba(255, 32, 32, 0.3);
  --alert-red-glow: rgba(255, 32, 32, 0.15);
  
  /* ===== Active primary (swapped by alert level) ===== */
  --primary: var(--alert-green);
  --primary-dim: var(--alert-green-dim);
  --primary-glow: var(--alert-green-glow);
  
  /* ===== Functional colours (do not change with alert) ===== */
  --friendly: #00aaff;
  --friendly-dim: rgba(0, 170, 255, 0.3);
  --hostile: #ff3333;
  --hostile-dim: rgba(255, 51, 51, 0.3);
  --neutral: #888888;
  --neutral-dim: rgba(136, 136, 136, 0.3);
  --unknown: #ffff00;
  --unknown-dim: rgba(255, 255, 0, 0.3);
  
  /* ===== System status ===== */
  --system-healthy: #00ff41;
  --system-warning: #ffb000;
  --system-critical: #ff2020;
  --system-offline: #444444;
  --hull-damage: #ff6600;
  
  /* ===== Text ===== */
  --text-bright: var(--primary);
  --text-normal: color-mix(in srgb, var(--primary) 70%, transparent);
  --text-dim: color-mix(in srgb, var(--primary) 40%, transparent);
  --text-muted: #555555;
  
  /* ===== Borders and lines ===== */
  --border-primary: var(--primary-dim);
  --border-bright: var(--primary);
  --grid-line: rgba(255, 255, 255, 0.05);
}
```

### Alert Level Switching

When the Captain sets the alert level, swap the `--primary` family:

```javascript
// Apply to document root
function setAlertLevel(level) {
  const root = document.documentElement;
  root.style.setProperty('--primary', `var(--alert-${level})`);
  root.style.setProperty('--primary-dim', `var(--alert-${level}-dim)`);
  root.style.setProperty('--primary-glow', `var(--alert-${level}-glow)`);
}
```

This instantly recolours every element using `var(--primary)` across the entire station.

### Colour Usage Rules

- **Primary** (`--primary`): Interactive elements, active indicators, important text, borders
- **Friendly** (`--friendly`): Allied ships, starbases, positive status
- **Hostile** (`--hostile`): Enemy contacts, damage indicators, warnings
- **Neutral** (`--neutral`): Inactive elements, disabled controls, background text
- **Unknown** (`--unknown`): Unscanned contacts, uncertain data
- Never use colours outside this palette. Every pixel should feel like it belongs to the same instrument.

---

## Typography

### Font Stack

```css
/* Primary font — used everywhere */
font-family: 'Share Tech Mono', 'Courier New', 'Consolas', monospace;

/* Load from Google Fonts */
@import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&display=swap');
```

### Text Styles

```css
/* Station headers / titles */
.text-title {
  font-size: 1.5rem;
  text-transform: uppercase;
  letter-spacing: 0.15em;
  color: var(--text-bright);
  text-shadow: 0 0 10px var(--primary-glow);
}

/* Panel headers */
.text-header {
  font-size: 0.85rem;
  text-transform: uppercase;
  letter-spacing: 0.2em;
  color: var(--text-normal);
}

/* Data readouts (numbers) */
.text-data {
  font-variant-numeric: tabular-nums;
  color: var(--text-bright);
}

/* Labels and descriptions */
.text-label {
  font-size: 0.75rem;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: var(--text-dim);
}

/* Body/description text */
.text-body {
  font-size: 0.85rem;
  color: var(--text-normal);
  line-height: 1.5;
}
```

### Text Rules

- ALL headings and labels are `text-transform: uppercase`
- Data readouts use `tabular-nums` for aligned numbers
- No serif fonts. No sans-serif. Monospace only.
- Letter-spacing on headers creates the military stencil feel

---

## Visual Effects

### Scanline Overlay

Applied to the `<body>` as a pseudo-element. Subtle, not distracting.

```css
body::after {
  content: '';
  position: fixed;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
  z-index: 9999;
  background: repeating-linear-gradient(
    0deg,
    transparent,
    transparent 2px,
    rgba(0, 0, 0, 0.08) 2px,
    rgba(0, 0, 0, 0.08) 4px
  );
}
```

### Glow Effects

Apply sparingly — to key interactive elements, active indicators, and important data. Not to everything.

```css
/* Text glow */
text-shadow: 0 0 8px var(--primary-glow);

/* Border glow */
box-shadow: 0 0 6px var(--primary-glow), inset 0 0 6px var(--primary-glow);

/* Strong glow (for active/important elements) */
box-shadow: 0 0 10px var(--primary-dim), 0 0 20px var(--primary-glow);
```

### Panel Borders

```css
.panel {
  background: var(--bg-panel);
  border: 1px solid var(--border-primary);
  box-shadow: 0 0 6px var(--primary-glow), inset 0 0 6px var(--primary-glow);
}

.panel__header {
  background: var(--bg-panel-header);
  border-bottom: 1px solid var(--border-primary);
  padding: 0.5rem 1rem;
}
```

### Subtle Flicker

Very subtle opacity animation on panel borders. 1-2% variation, not distracting. Optional — apply to outer container only.

```css
@keyframes flicker {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.98; }
}

.station-container {
  animation: flicker 4s infinite;
}
```

### Hit Flash

When the ship takes damage, briefly flash the screen border.

```css
@keyframes hit-flash {
  0% { box-shadow: inset 0 0 50px var(--hostile-dim); }
  100% { box-shadow: inset 0 0 0px transparent; }
}

.station-container.hit {
  animation: hit-flash 0.3s ease-out;
}
```

---

## Canvas Rendering Conventions

### General Rules

- All entities rendered as **wireframe outlines**, never filled
- Use `ctx.strokeStyle`, not `ctx.fillStyle` (exception: translucent glow fills)
- Line width: 1-2px for most elements, 2-3px for the player ship
- Clear canvas fully each frame (`ctx.clearRect`)
- Dark background (draw `--bg-primary` fill as first operation)

### Grid Lines

Faint grid on all canvas displays (radar, maps, viewscreen):

```javascript
function drawGrid(ctx, spacing, colour = 'rgba(255, 255, 255, 0.05)') {
  ctx.strokeStyle = colour;
  ctx.lineWidth = 0.5;
  // Draw vertical and horizontal lines at regular spacing
  // Offset by camera position for scrolling effect
}
```

### Entity Shapes

Consistent shapes across all displays:

```
Player ship:    Chevron/arrow pointing in heading direction
                  /\
                 /  \
                /____\

Enemy Scout:    Diamond (small)
                  ◇

Enemy Cruiser:  Triangle (medium)
                  △

Enemy Destroyer: Hexagon (large)
                  ⬡

Space Station:  Circle with cross
                  ⊕

Torpedo:        Small dot with trailing line
                  ·---

Waypoint:       Hollow square
                  □

Asteroid:       Irregular polygon (4-6 sides, slightly randomised)

Unknown:        Question mark or simple dot
                  ?
```

### Rendering Details

- **Beams**: Bright line from source to target, using `--primary` colour at full opacity. Fade out over 200ms (reduce alpha per frame).
- **Torpedoes**: Small bright dot (`--hostile` for enemy, `--primary` for player) with a 3-5 point trailing line showing previous positions.
- **Shield hits**: Arc flash at the impact point on the shield perimeter. Bright flash fading over 300ms.
- **Explosions**: Expanding wireframe circle that fades. 3-4 concentric rings expanding at different rates.
- **Scan sweep**: Rotating line on the sensor display, like a radar sweep. Contacts brighten as the sweep passes over them.
- **Starfield**: Points of varying brightness. Parallax scrolling (background stars move slower than foreground). Stars rendered as 1px dots with occasional 2px bright stars.

### Canvas Coordinate System

- World coordinates: Arbitrary units, origin at sector centre (0, 0)
- Screen coordinates: Canvas pixels, origin at top-left (0, 0)
- Transform: `screenX = (worldX - cameraX) * zoom + canvas.width / 2`
- All positions stored as world coordinates; transform at render time only

---

## UI Components

### Buttons

```css
.btn {
  background: transparent;
  border: 1px solid var(--border-primary);
  color: var(--text-normal);
  padding: 0.5rem 1.5rem;
  font-family: inherit;
  font-size: 0.8rem;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  cursor: pointer;
  transition: all 0.2s;
}

.btn:hover {
  border-color: var(--primary);
  color: var(--text-bright);
  box-shadow: 0 0 8px var(--primary-glow);
}

.btn--primary {
  border-color: var(--primary);
  color: var(--text-bright);
}

.btn--danger {
  border-color: var(--hostile);
  color: var(--hostile);
}

.btn:disabled {
  border-color: var(--neutral-dim);
  color: var(--text-muted);
  cursor: not-allowed;
  box-shadow: none;
}
```

### Sliders / Range Inputs

Style range inputs to look like instrument controls — thin track, bright thumb.

### Gauges

For health bars, power levels, etc:

```css
.gauge {
  background: var(--bg-secondary);
  border: 1px solid var(--border-primary);
  height: 8px;
  position: relative;
}

.gauge__fill {
  height: 100%;
  transition: width 0.3s;
  /* Colour set dynamically based on value: green > yellow > red */
}
```

### Connection Status Indicator

Three states:

```css
.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

.status-dot--connected {
  background: var(--system-healthy);
  box-shadow: 0 0 6px var(--system-healthy);
}

.status-dot--reconnecting {
  background: var(--system-warning);
  animation: pulse 1s infinite;
}

.status-dot--disconnected {
  background: var(--system-critical);
}
```

---

## Layout Principles

- Dark background everywhere. No white space. No light themes.
- Panels arranged in a grid appropriate to the station's needs
- Minimal padding — information density is a feature, not a bug
- Canvas elements should take up the maximum available space
- Controls clustered by function, not spread across the screen
- Responsive: panels stack vertically on narrow viewports (tablets)
- Minimum supported width: 768px (tablet portrait)

---

## What This Aesthetic is NOT

- Not "dark mode" of a normal web app — it's a purpose-built instrument display
- Not retro for retro's sake — it's functional minimalism
- Not placeholder — this IS the art style
- Not a game UI with health bars and inventories — it's a bridge console
- Not colourful — the limited palette is intentional. Colour means something.
