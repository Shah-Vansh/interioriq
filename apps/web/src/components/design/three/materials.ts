// Procedural PBR materials for the realistic 3D view — every texture is drawn on a canvas in the browser (no downloads, zero cost).
import * as THREE from 'three'

const cache = new Map<string, THREE.Texture>()
function canvasTex(key: string, size: number, draw: (g: CanvasRenderingContext2D, s: number) => void, repeat: [number, number] = [1, 1]) {
  const k = `${key}:${repeat.join('x')}`
  let t = cache.get(k)
  if (t) return t
  const c = document.createElement('canvas'); c.width = c.height = size
  const g = c.getContext('2d')!; draw(g, size)
  t = new THREE.CanvasTexture(c); t.wrapS = t.wrapT = THREE.RepeatWrapping; t.repeat.set(...repeat)
  t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 8; cache.set(k, t); return t
}
let seed = 7
const rnd = () => { seed = (seed * 16807) % 2147483647; return seed / 2147483647 }

/** Wood grain (long streaks + rings), drawn light-on-dark so a colour tint keeps the grain. */
export function woodTexture(tone = '#8b5a2b', repeat: [number, number] = [1, 1]) {
  return canvasTex(`wood-${tone}`, 512, (g, s) => {
    g.fillStyle = tone; g.fillRect(0, 0, s, s)
    for (let i = 0; i < 160; i++) {
      const y = rnd() * s, a = 0.04 + rnd() * 0.08, w = 0.6 + rnd() * 2.2
      g.strokeStyle = rnd() > 0.5 ? `rgba(0,0,0,${a})` : `rgba(255,240,220,${a * 0.7})`; g.lineWidth = w; g.beginPath(); g.moveTo(0, y)
      for (let x = 0; x <= s; x += 16) g.lineTo(x, y + Math.sin(x / (40 + rnd() * 30) + i) * (2 + rnd() * 3))
      g.stroke()
    }
    for (let k = 0; k < 6; k++) { g.strokeStyle = 'rgba(40,20,5,0.12)'; g.lineWidth = 1.2; g.beginPath(); g.ellipse(rnd() * s, rnd() * s, 18 + rnd() * 30, 4 + rnd() * 6, 0, 0, Math.PI * 2); g.stroke() }
  }, repeat)
}

/** Plank floor: planks of slightly different tone with joints. */
export function floorTexture(tone = '#b88a5a', repeat: [number, number] = [2, 2]) {
  return canvasTex(`floor-${tone}`, 1024, (g, s) => {
    const rows = 8, h = s / rows
    for (let r = 0; r < rows; r++) {
      let x = -rnd() * 300
      while (x < s) {
        const w = 260 + rnd() * 260, shade = 0.85 + rnd() * 0.25
        const c = new THREE.Color(tone).multiplyScalar(shade); g.fillStyle = `#${c.getHexString()}`; g.fillRect(x, r * h, w, h)
        for (let i = 0; i < 14; i++) { g.strokeStyle = `rgba(0,0,0,${0.03 + rnd() * 0.05})`; g.lineWidth = 1; const yy = r * h + rnd() * h; g.beginPath(); g.moveTo(x, yy); g.lineTo(x + w, yy + (rnd() - 0.5) * 4); g.stroke() }
        g.fillStyle = 'rgba(0,0,0,0.35)'; g.fillRect(x, r * h, 2, h); x += w
      }
      g.fillStyle = 'rgba(0,0,0,0.35)'; g.fillRect(0, r * h, s, 2)
    }
  }, repeat)
}

/** Woven fabric (fine cross-hatch + noise). */
export function fabricTexture(tone = '#9ca3af') {
  return canvasTex(`fabric-${tone}`, 256, (g, s) => {
    g.fillStyle = tone; g.fillRect(0, 0, s, s)
    for (let i = 0; i < s; i += 3) { g.fillStyle = `rgba(255,255,255,${0.04 + rnd() * 0.04})`; g.fillRect(i, 0, 1, s); g.fillStyle = `rgba(0,0,0,${0.04 + rnd() * 0.04})`; g.fillRect(0, i, s, 1) }
    for (let i = 0; i < 2500; i++) { g.fillStyle = `rgba(0,0,0,${rnd() * 0.06})`; g.fillRect(rnd() * s, rnd() * s, 1, 1) }
  }, [3, 3])
}

/** Marble / quartz with soft veins. */
export function marbleTexture(tone = '#f1f0ee') {
  return canvasTex(`marble-${tone}`, 512, (g, s) => {
    g.fillStyle = tone; g.fillRect(0, 0, s, s)
    for (let v = 0; v < 9; v++) {
      g.strokeStyle = `rgba(90,90,100,${0.08 + rnd() * 0.12})`; g.lineWidth = 0.6 + rnd() * 2; g.beginPath()
      let x = rnd() * s, y = 0; g.moveTo(x, y)
      while (y < s) { x += (rnd() - 0.5) * 40; y += 10 + rnd() * 20; g.lineTo(x, y) }
      g.stroke()
    }
  })
}

/** Ceramic wall tiles with grout lines. */
export function tileTexture(tone = '#e7e5e4', repeat: [number, number] = [4, 4]) {
  return canvasTex(`tile-${tone}`, 256, (g, s) => {
    g.fillStyle = '#c8c4bd'; g.fillRect(0, 0, s, s)
    const n = 2, w = s / n
    for (let i = 0; i < n; i++) for (let j = 0; j < n; j++) {
      const c = new THREE.Color(tone).multiplyScalar(0.96 + rnd() * 0.06); g.fillStyle = `#${c.getHexString()}`; g.fillRect(i * w + 2, j * w + 2, w - 4, w - 4)
    }
  }, repeat)
}

/** Faint plaster noise for painted walls / ceiling. */
export function plasterTexture(tone = '#f3efe8') {
  return canvasTex(`plaster-${tone}`, 256, (g, s) => {
    g.fillStyle = tone; g.fillRect(0, 0, s, s)
    for (let i = 0; i < 4000; i++) { g.fillStyle = rnd() > 0.5 ? `rgba(0,0,0,${rnd() * 0.025})` : `rgba(255,255,255,${rnd() * 0.04})`; g.fillRect(rnd() * s, rnd() * s, 2, 2) }
  }, [3, 3])
}

// ── material factory (cached by key) ─────────────────────────────────────────
const mats = new Map<string, THREE.Material>()
function get<T extends THREE.Material>(key: string, make: () => T): T { let m = mats.get(key) as T | undefined; if (!m) { m = make(); mats.set(key, m) } return m }


/** Repeating wallpaper motif (leaf / lattice) in the accent colour on a light ground. */
export function wallpaperTexture(tone = '#6b4a32') {
  return canvasTex(`wallpaper-${tone}`, 256, (g, s) => {
    const base = new THREE.Color(tone).lerp(new THREE.Color('#ffffff'), 0.82); g.fillStyle = `#${base.getHexString()}`; g.fillRect(0, 0, s, s)
    g.strokeStyle = tone; g.fillStyle = tone; g.globalAlpha = 0.55; g.lineWidth = 2
    for (let i = 0; i < 2; i++) for (let j = 0; j < 2; j++) {
      const cx = s / 4 + i * s / 2, cy = s / 4 + j * s / 2
      g.beginPath(); g.moveTo(cx, cy - 40); g.quadraticCurveTo(cx + 34, cy, cx, cy + 40); g.quadraticCurveTo(cx - 34, cy, cx, cy - 40); g.fill()
      g.beginPath(); g.moveTo(cx, cy - 46); g.lineTo(cx, cy + 50); g.stroke()
    }
    g.globalAlpha = 1
  }, [6, 4])
}
/** Random-ashlar stone cladding. */
export function stoneTexture(tone = '#b9ab95') {
  return canvasTex(`stone-${tone}`, 512, (g, s) => {
    g.fillStyle = '#6b665e'; g.fillRect(0, 0, s, s)
    let y = 0
    while (y < s) {
      const h = 40 + rnd() * 50; let x = -rnd() * 60
      while (x < s) { const w = 60 + rnd() * 140; const c = new THREE.Color(tone).multiplyScalar(0.78 + rnd() * 0.35); g.fillStyle = `#${c.getHexString()}`; g.fillRect(x + 3, y + 3, w - 6, h - 6); x += w }
      y += h
    }
  }, [2, 2])
}
/** Exposed brick. */
export function brickTexture(tone = '#8e4b36') {
  return canvasTex(`brick-${tone}`, 512, (g, s) => {
    g.fillStyle = '#cfc6b8'; g.fillRect(0, 0, s, s)
    const bh = 32, bw = 96
    for (let r = 0; r * bh < s; r++) for (let x = (r % 2) * -bw / 2; x < s; x += bw) {
      const c = new THREE.Color(tone).multiplyScalar(0.75 + rnd() * 0.4); g.fillStyle = `#${c.getHexString()}`; g.fillRect(x + 2, r * bh + 2, bw - 4, bh - 4)
    }
  }, [2, 3])
}
/** Jaali lattice (light shows through the gaps — used with an emissive back panel). */
export function jaaliTexture(tone = '#8a5a2b') {
  return canvasTex(`jaali-${tone}`, 256, (g, s) => {
    g.fillStyle = tone; g.fillRect(0, 0, s, s); g.fillStyle = '#fff1d6'
    const n = 4, c = s / n
    for (let i = 0; i < n; i++) for (let j = 0; j < n; j++) {
      const x = i * c + c / 2, y = j * c + c / 2
      g.beginPath(); for (let k = 0; k < 8; k++) { const a = k * Math.PI / 4, r = k % 2 ? c * 0.18 : c * 0.36; g.lineTo(x + Math.cos(a) * r, y + Math.sin(a) * r) } g.closePath(); g.fill()
    }
  }, [3, 4])
}
/** Terrazzo chips. */
export function terrazzoTexture(tone = '#e6ddd0') {
  return canvasTex(`terrazzo-${tone}`, 512, (g, s) => {
    g.fillStyle = tone; g.fillRect(0, 0, s, s)
    const chips = ['#b5603c', '#7d8f69', '#3f3f46', '#d6d3d1', '#c7a24a']
    for (let i = 0; i < 900; i++) { g.fillStyle = chips[Math.floor(rnd() * chips.length)]; g.beginPath(); g.ellipse(rnd() * s, rnd() * s, 2 + rnd() * 7, 1.5 + rnd() * 5, rnd() * 3, 0, Math.PI * 2); g.fill() }
  }, [3, 3])
}
/** Rug with a border and a simple pattern. */
export function rugTexture(tone = '#8a8f96') {
  return canvasTex(`rug-${tone}`, 512, (g, s) => {
    const base = new THREE.Color(tone), light = base.clone().lerp(new THREE.Color('#ffffff'), 0.45), dark = base.clone().multiplyScalar(0.6)
    g.fillStyle = `#${light.getHexString()}`; g.fillRect(0, 0, s, s)
    g.strokeStyle = `#${base.getHexString()}`; g.lineWidth = 28; g.strokeRect(30, 30, s - 60, s - 60)
    g.strokeStyle = `#${dark.getHexString()}`; g.lineWidth = 6; g.strokeRect(62, 62, s - 124, s - 124)
    g.fillStyle = `#${base.getHexString()}`
    for (let i = 0; i < 5; i++) for (let j = 0; j < 5; j++) { const x = 110 + i * 73, y = 110 + j * 73; g.beginPath(); g.moveTo(x, y - 18); g.lineTo(x + 18, y); g.lineTo(x, y + 18); g.lineTo(x - 18, y); g.fill() }
    for (let i = 0; i < 6000; i++) { g.fillStyle = `rgba(0,0,0,${rnd() * 0.05})`; g.fillRect(rnd() * s, rnd() * s, 2, 2) }
  })
}
/** Abstract painting from a palette. */
export function artTexture(colours: string[]) {
  return canvasTex(`art-${colours.join('')}`, 512, (g, s) => {
    g.fillStyle = '#f4f1ea'; g.fillRect(0, 0, s, s)
    colours.forEach((c, i) => { g.fillStyle = c; g.globalAlpha = 0.85; g.beginPath(); g.ellipse(s * (0.3 + 0.2 * i), s * (0.35 + 0.15 * (i % 2)), s * (0.28 - 0.05 * i), s * (0.2 + 0.04 * i), i * 0.6, 0, Math.PI * 2); g.fill() })
    g.globalAlpha = 1; g.strokeStyle = colours[0]; g.lineWidth = 6; g.beginPath(); g.moveTo(s * 0.1, s * 0.8); g.bezierCurveTo(s * 0.4, s * 0.55, s * 0.6, s * 0.95, s * 0.9, s * 0.7); g.stroke()
  })
}

export const M = {
  wood: (tone = '#7a4a24') => get(`wood${tone}`, () => new THREE.MeshStandardMaterial({ map: woodTexture(tone, [2, 2]), roughness: 0.55, metalness: 0 })),
  laminate: (tone = '#e9e4dc') => get(`lam${tone}`, () => new THREE.MeshStandardMaterial({ color: tone, roughness: 0.42, metalness: 0 })),
  fabric: (tone = '#8f9aa6') => get(`fab${tone}`, () => new THREE.MeshStandardMaterial({ map: fabricTexture(tone), roughness: 0.95, metalness: 0 })),
  linen: () => get('linen', () => new THREE.MeshStandardMaterial({ map: fabricTexture('#f4f1ea'), roughness: 0.9 })),
  metal: () => get('metal', () => new THREE.MeshStandardMaterial({ color: '#a8a29e', roughness: 0.3, metalness: 0.9 })),
  black: () => get('blackmetal', () => new THREE.MeshStandardMaterial({ color: '#1c1917', roughness: 0.4, metalness: 0.6 })),
  chrome: () => get('chrome', () => new THREE.MeshStandardMaterial({ color: '#d4d7dc', roughness: 0.28, metalness: 0.75 })),
  ceramic: () => get('ceramic', () => new THREE.MeshPhysicalMaterial({ color: '#fbfbf9', roughness: 0.12, clearcoat: 1, clearcoatRoughness: 0.08 })),
  quartz: () => get('quartz', () => new THREE.MeshPhysicalMaterial({ map: marbleTexture(), roughness: 0.22, clearcoat: 0.6 })),
  glass: () => get('glass', () => new THREE.MeshPhysicalMaterial({ color: '#dbeafe', roughness: 0.04, metalness: 0, transmission: 0.92, thickness: 0.01, transparent: true, opacity: 0.35, ior: 1.5 })),
  mirror: () => get('mirror', () => new THREE.MeshStandardMaterial({ color: '#c3d1db', roughness: 0.1, metalness: 0.55, envMapIntensity: 1.6 })),
  screen: () => get('screen', () => new THREE.MeshStandardMaterial({ color: '#0b0b0d', roughness: 0.15, metalness: 0.3 })),
  appliance: () => get('appliance', () => new THREE.MeshStandardMaterial({ color: '#f5f5f4', roughness: 0.3, metalness: 0.2 })),
  leaf: () => get('leaf', () => new THREE.MeshStandardMaterial({ color: '#3f6b35', roughness: 0.8 })),
  pot: () => get('pot', () => new THREE.MeshStandardMaterial({ color: '#c2b8a3', roughness: 0.7 })),
  emissive: () => get('lamp', () => new THREE.MeshStandardMaterial({ color: '#fff7e6', emissive: '#fff1d6', emissiveIntensity: 2.2 })),
  red: () => get('flag', () => new THREE.MeshBasicMaterial({ color: '#dc2626', transparent: true, opacity: 0.35, depthWrite: false })),
  hit: () => get('hit', () => new THREE.MeshBasicMaterial({ transparent: true, opacity: 0, depthWrite: false })),
  floor: (tone = '#b88a5a', l = 4, w = 4) => get(`floor${tone}${l.toFixed(1)}x${w.toFixed(1)}`, () => new THREE.MeshStandardMaterial({ map: floorTexture(tone, [Math.max(1, l / 2), Math.max(1, w / 2)]), roughness: 0.5 })),
  tiles: (tone = '#e7e5e4', l = 2, w = 2) => get(`tiles${tone}${l.toFixed(1)}x${w.toFixed(1)}`, () => new THREE.MeshStandardMaterial({ map: tileTexture(tone, [Math.max(1, l * 1.7), Math.max(1, w * 1.7)]), roughness: 0.25 })),
  ceiling: () => get('ceiling', () => new THREE.MeshStandardMaterial({ map: plasterTexture('#faf8f4'), roughness: 0.95, emissive: '#efe9df', emissiveIntensity: 0.32 })),
  wallpaper: (tone = '#6b4a32') => get(`wp${tone}`, () => new THREE.MeshStandardMaterial({ map: wallpaperTexture(tone), roughness: 0.85 })),
  stone: (tone = '#b9ab95') => get(`stone${tone}`, () => new THREE.MeshStandardMaterial({ map: stoneTexture(tone), roughness: 0.9 })),
  brick: (tone = '#8e4b36') => get(`brick${tone}`, () => new THREE.MeshStandardMaterial({ map: brickTexture(tone), roughness: 0.95 })),
  jaali: (tone = '#8a5a2b') => get(`jaali${tone}`, () => new THREE.MeshStandardMaterial({ map: jaaliTexture(tone), emissiveMap: jaaliTexture(tone), emissive: '#ffd9a0', emissiveIntensity: 0.6, roughness: 0.7 })),
  terrazzo: (tone = '#e6ddd0') => get(`terr${tone}`, () => new THREE.MeshStandardMaterial({ map: terrazzoTexture(tone), roughness: 0.3 })),
  marbleFloor: () => get('marblefloor', () => new THREE.MeshPhysicalMaterial({ map: marbleTexture('#efeae2'), roughness: 0.15, clearcoat: 0.5 })),
  paint: (tone = '#6b4a32') => get(`paint${tone}`, () => new THREE.MeshStandardMaterial({ color: tone, roughness: 0.85 })),
  rug: (tone = '#8a8f96') => get(`rug${tone}`, () => new THREE.MeshStandardMaterial({ map: rugTexture(tone), roughness: 1 })),
  art: (colours: string[]) => get(`art${colours.join('')}`, () => new THREE.MeshStandardMaterial({ map: artTexture(colours), roughness: 0.7 })),
  curtain: (tone = '#cfc6b8') => get(`curtain${tone}`, () => new THREE.MeshStandardMaterial({ map: fabricTexture(tone), roughness: 0.95, side: THREE.DoubleSide })),
  led: () => get('led', () => new THREE.MeshStandardMaterial({ color: '#fff4dc', emissive: '#ffe7b8', emissiveIntensity: 3 })),
  wall: (tone = '#f3efe8') => get(`wall${tone}`, () => new THREE.MeshStandardMaterial({ map: plasterTexture(tone), roughness: 0.92 })),
}

/** A user-picked colour turns into the right finish for the part. */
export function finish(kind: 'wood' | 'laminate' | 'fabric', colour?: string | null, fallback?: string) {
  const c = colour || fallback
  return kind === 'wood' ? M.wood(c ?? '#7a4a24') : kind === 'fabric' ? M.fabric(c ?? '#8f9aa6') : M.laminate(c ?? '#e9e4dc')
}
