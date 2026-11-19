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
  wall: (tone = '#f3efe8') => get(`wall${tone}`, () => new THREE.MeshStandardMaterial({ map: plasterTexture(tone), roughness: 0.92 })),
}

/** A user-picked colour turns into the right finish for the part. */
export function finish(kind: 'wood' | 'laminate' | 'fabric', colour?: string | null, fallback?: string) {
  const c = colour || fallback
  return kind === 'wood' ? M.wood(c ?? '#7a4a24') : kind === 'fabric' ? M.fabric(c ?? '#8f9aa6') : M.laminate(c ?? '#e9e4dc')
}
