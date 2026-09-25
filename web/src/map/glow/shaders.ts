/**
 * GLSL ES 3.00 sources for the glow layer.
 *
 * - Light: one point sprite per glowing point, a soft radial kernel added
 *   into an offscreen light target, one status per channel. The target is
 *   half-float; in the 8-bit fallback each point's light is written as
 *   1 - exp(-light * alpha) with screen blending, which adds light in
 *   optical depth, so 8 bits roll off smoothly where they would clip, into a
 *   coarse and a fine target at once (see FALLBACK_ALPHA_STOPS).
 * - Bloom: a 2x downsample chain of the light target and a tent-filtered
 *   upsample chain that adds each scale back with its weight. The first
 *   downsample eases light past a knee, so no stack of points, however tall,
 *   blooms without bound.
 * - Composite: a full-screen triangle that turns per-status light into linear
 *   RGB, tone maps it and screens it onto the map.
 * - Glyph: crisp per-status SDF shapes drawn at full resolution from zoom 11.
 *
 * Points are drawn as gl.POINTS sprites rather than instanced quads: one
 * vertex per point and no per-instance setup. With SwiftShader, 30,000
 * instanced quads cost about 300 ms of pure per-instance overhead a frame
 * even when every quad is off screen; the same sprites cost about 7 ms.
 */
import { STATUS_COUNT } from './color';
import {
  BLOOM_SOURCE_GLSL,
  CORE_EDGE_D2,
  FALLBACK_FINE_GAIN,
  FALLBACK_GLSL,
  PULSE_GLSL,
} from './curves';
import { TONEMAP_GLSL } from './tonemap';

/** Attribute locations, fixed so every program shares one VAO layout. */
export const ATTRIB = { hi: 0, lo: 1, born: 2, status: 3 } as const;

/** Diamond half-diagonal relative to the dot radius, for matching visual weight. */
export const DIAMOND_SCALE = 1.2;
/** Open dots are faint. */
export const OPEN_ALPHA = 0.85;
/** Anti-aliasing margin around a glyph, device px. */
export const GLYPH_AA_PX = 1.5;

const POINT_PRELUDE = /* glsl */ `#version 300 es
precision highp float;
precision highp int;

layout(location = ${String(ATTRIB.hi)}) in vec2 a_hi;
layout(location = ${String(ATTRIB.lo)}) in vec2 a_lo;
layout(location = ${String(ATTRIB.born)}) in float a_born;
layout(location = ${String(ATTRIB.status)}) in uint a_status;

// Mercator (relative to u_origin) to clip space, built in float64 on the CPU.
uniform mat4 u_matrix;
uniform vec2 u_origin;
// Maps the map's NDC into the surface being drawn, which is larger than the
// map by a margin so points just off screen still reach it.
uniform vec2 u_ndcScale;
uniform float u_maxPointSize;
// Layer clock in seconds, and 0 to disable the pulse (reduced motion).
uniform float u_now;
uniform float u_motion;

const float PI = 3.141592653589793;
${PULSE_GLSL}

// x: brightness multiplier, y: radius multiplier.
vec2 glow_pulse() {
  if (u_motion < 0.5) return vec2(1.0);
  float t = (u_now - a_born) / GLOW_PULSE_SECONDS;
  if (t >= 1.0) return vec2(1.0);
  if (t < 0.0) return vec2(0.0, 1.0);
  float s = sin(PI * t);
  float swell = s * s * (1.0 - t);
  return vec2(smoothstep(0.0, 0.12, t) * (1.0 + GLOW_PULSE_GAIN * swell), 1.0 + GLOW_PULSE_GROW * swell);
}

// Places the sprite, or parks it outside the clip volume. Subtracting the
// float32 origin from the hi part first is exact near the camera; the lo part
// then restores the bits float32 dropped.
void glow_place(float diameter) {
  vec4 clip = u_matrix * vec4((a_hi - u_origin) + a_lo, 0.0, 1.0);
  if (clip.w <= 0.0 || diameter <= 0.0) {
    gl_Position = vec4(2.0, 2.0, 2.0, 1.0);
    gl_PointSize = 1.0;
    return;
  }
  gl_Position = vec4(clip.xy / clip.w * u_ndcScale, 0.0, 1.0);
  gl_PointSize = min(diameter, u_maxPointSize);
}
`;

export const LIGHT_VERT = /* glsl */ `${POINT_PRELUDE}
uniform float u_radius;
uniform float u_gain;

out vec4 v_light;

void main() {
  vec2 pulse = glow_pulse();
  // One status per channel: closed, delayed, remote, early dismissal.
  v_light = vec4(equal(uvec4(a_status), uvec4(0u, 1u, 2u, 3u))) * (u_gain * pulse.x);
  glow_place(pulse.x > 0.0 ? 2.0 * u_radius * pulse.y : 0.0);
}
`;

export const LIGHT_FRAG = /* glsl */ `#version 300 es
precision highp float;

uniform float u_coreFalloff;
uniform float u_coreWeight;
uniform float u_haloFalloff;
uniform float u_haloWeight;
// Normalized radius inside which the halo is cut away so a glyph's halo
// never fills its center; 0 below glyph zoom.
uniform float u_hole;
// 0: add linear light (half-float target). Otherwise the 8-bit fallback's
// alpha: light is written as 1 - exp(-light * alpha), screen blended, to a
// coarse target and to a fine one at a higher alpha.
uniform float u_encode;

const float CORE_EDGE = ${String(CORE_EDGE_D2)};

in vec4 v_light;
layout(location = 0) out vec4 fragColor;
layout(location = 1) out vec4 fragFine;

void main() {
  vec2 uv = gl_PointCoord * 2.0 - 1.0;
  float d2 = dot(uv, uv);
  if (d2 >= 1.0) discard;
  // The core fades to exactly zero over the sprite's outer quarter, so a lone
  // speck has no visible edge where its sprite ends.
  float k = u_coreWeight * exp(-d2 * u_coreFalloff) * (1.0 - smoothstep(CORE_EDGE, 1.0, d2));
  if (u_haloWeight > 0.0) {
    float window = 1.0 - d2;
    float halo = u_haloWeight * exp(-d2 * u_haloFalloff) * window * window;
    if (u_hole > 0.0) halo *= smoothstep(u_hole * 0.75, u_hole * 1.1, sqrt(d2));
    k += halo;
  }
  vec4 light = v_light * k;
  if (u_encode > 0.0) {
    fragColor = 1.0 - exp(-light * u_encode);
    fragFine = 1.0 - exp(-light * (u_encode * ${FALLBACK_FINE_GAIN.toFixed(1)}));
  } else {
    fragColor = light;
    fragFine = vec4(0.0);
  }
}
`;

/** Full-screen triangle; v_uv spans 0..1 over the viewport. */
export const FULLSCREEN_VERT = /* glsl */ `#version 300 es
precision highp float;
out vec2 v_uv;
void main() {
  vec2 p = vec2(float((gl_VertexID << 1) & 2), float(gl_VertexID & 2));
  v_uv = p;
  gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0);
}
`;

/**
 * 2x downsample: four bilinear taps one source texel off each diagonal, a
 * 4x4 box that keeps a moving speck's light steady across coarse texels.
 * From the light target itself (u_limit 1), each tap is first eased past the
 * bloom knee.
 */
export const DOWNSAMPLE_FRAG = /* glsl */ `#version 300 es
precision highp float;
uniform sampler2D u_source;
uniform vec2 u_texel;
uniform float u_limit;
in vec2 v_uv;
out vec4 fragColor;
${BLOOM_SOURCE_GLSL}
vec4 tap(vec2 uv) {
  vec4 light = texture(u_source, uv);
  return u_limit > 0.5 ? glow_bloom_source(light) : light;
}
void main() {
  vec4 sum = tap(v_uv + vec2(-u_texel.x, -u_texel.y))
           + tap(v_uv + vec2( u_texel.x, -u_texel.y))
           + tap(v_uv + vec2(-u_texel.x,  u_texel.y))
           + tap(v_uv + vec2( u_texel.x,  u_texel.y));
  fragColor = sum * 0.25;
}
`;

/**
 * 2x upsample with a 3x3 tent over the coarse level (four bilinear taps half
 * a texel off each diagonal), scaled by u_scale. It is blended onto the finer
 * level with that level's own bloom weight as the constant blend factor, so
 * each pass leaves weight * level + everything coarser.
 */
export const UPSAMPLE_FRAG = /* glsl */ `#version 300 es
precision highp float;
uniform sampler2D u_source;
uniform vec2 u_texel;
uniform float u_scale;
in vec2 v_uv;
out vec4 fragColor;
void main() {
  vec2 h = 0.5 * u_texel;
  vec4 sum = texture(u_source, v_uv + vec2(-h.x, -h.y))
           + texture(u_source, v_uv + vec2( h.x, -h.y))
           + texture(u_source, v_uv + vec2(-h.x,  h.y))
           + texture(u_source, v_uv + vec2( h.x,  h.y));
  fragColor = sum * (0.25 * u_scale);
}
`;

export const COMPOSITE_FRAG = /* glsl */ `#version 300 es
precision highp float;

// Core light, and the first bloom level holding every weighted scale of bloom.
uniform sampler2D u_light;
uniform sampler2D u_bloom;
// The 8-bit fallback's fine light target; unused on the float path.
uniform sampler2D u_lightFine;
uniform float u_bloomScale;
uniform vec2 u_bloomTexel;
// The light target has a guard band around the map; this picks the map's part.
uniform vec2 u_uvScale;
uniform vec2 u_uvOffset;
uniform float u_exposure;
// 0 for a half-float light target. Otherwise the 8-bit fallback's alpha, to
// turn its optical-depth encoding back into light.
uniform float u_decode;
// Linear-light tokens for closed, delayed, remote, early dismissal.
uniform vec3 u_tokens[4];

in vec2 v_uv;
out vec4 fragColor;
${TONEMAP_GLSL}
${FALLBACK_GLSL}
// Interleaved gradient noise (Jimenez 2014): cheap, even dither that breaks
// up 8-bit banding in the faint outer glow.
float glow_dither(vec2 p) {
  return fract(52.9829189 * fract(dot(p, vec2(0.06711056, 0.00583715))));
}

void main() {
  vec2 uv = u_uvOffset + v_uv * u_uvScale;
  vec4 light = texture(u_light, uv);
  if (u_decode > 0.0) light = glow_fallback_decode(light, texture(u_lightFine, uv), u_decode);
  if (u_bloomScale > 0.0) {
    // Four bilinear taps half a texel off each diagonal: a 3x3 tent upsample.
    vec2 h = 0.5 * u_bloomTexel;
    vec4 bloom = texture(u_bloom, uv + vec2(-h.x, -h.y))
               + texture(u_bloom, uv + vec2( h.x, -h.y))
               + texture(u_bloom, uv + vec2(-h.x,  h.y))
               + texture(u_bloom, uv + vec2( h.x,  h.y));
    light += bloom * (0.25 * u_bloomScale);
  }
  vec3 rgb = glow_status_light(light, u_tokens) * u_exposure;
  vec3 c = glow_linear_to_srgb(glow_tonemap(rgb));
  if (max(c.r, max(c.g, c.b)) <= 0.0) discard;
  c = clamp(c + (glow_dither(gl_FragCoord.xy) - 0.5) / 255.0, 0.0, 1.0);
  // Blended as screen: src + dst * (1 - src). Light never darkens the map.
  fragColor = vec4(c, 0.0);
}
`;

export const GLYPH_VERT = /* glsl */ `${POINT_PRELUDE}
uniform float u_glyphRadius;
uniform float u_openRadius;
uniform float u_opacity;

out float v_alpha;
out float v_half;
flat out uint v_status;
flat out float v_radius;

void main() {
  vec2 pulse = glow_pulse();
  float radius = a_status == 4u ? u_openRadius : u_glyphRadius;
  if (a_status == 2u) radius *= ${DIAMOND_SCALE.toFixed(2)};
  radius *= pulse.y;
  v_half = radius + ${GLYPH_AA_PX.toFixed(1)};
  v_alpha = u_opacity * min(pulse.x, 1.0);
  v_status = a_status;
  v_radius = radius;
  glow_place(pulse.x > 0.0 ? 2.0 * v_half : 0.0);
}
`;

export const GLYPH_FRAG = /* glsl */ `#version 300 es
precision highp float;
precision highp int;

// Display-space (sRGB) status colors: glyph fills are the tokens exactly.
uniform vec3 u_colors[${String(STATUS_COUNT)}];
uniform float u_ringWidth;

in float v_alpha;
in float v_half;
flat in uint v_status;
flat in float v_radius;
out vec4 fragColor;

void main() {
  vec2 p = (gl_PointCoord * 2.0 - 1.0) * v_half;
  float r = v_radius;
  float len = length(p);
  float ring = abs(len - (r - 0.5 * u_ringWidth)) - 0.5 * u_ringWidth;
  float d;
  if (v_status == 1u) {
    d = ring;                                         // delayed: ring
  } else if (v_status == 2u) {
    d = (abs(p.x) + abs(p.y) - r) * 0.70710678;       // remote: diamond
  } else if (v_status == 3u) {
    d = min(ring, max(len - r, p.x));                 // early dismissal: ring, left half filled
  } else {
    d = len - r;                                      // closed and open: filled dot
  }
  float coverage = clamp(0.5 - d, 0.0, 1.0) * v_alpha;
  if (v_status == 4u) coverage *= ${OPEN_ALPHA.toFixed(2)};
  if (coverage <= 0.0) discard;
  fragColor = vec4(u_colors[v_status] * coverage, coverage);
}
`;
