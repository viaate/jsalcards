/** Small WebGL2 helpers for the glow layer. */

export interface Program {
  readonly program: WebGLProgram;
  readonly uniforms: ReadonlyMap<string, WebGLUniformLocation>;
}

function compile(
  gl: WebGL2RenderingContext,
  type: GLenum,
  source: string,
  label: string,
): WebGLShader {
  const shader = gl.createShader(type);
  if (shader === null) throw new Error(`glow: could not create the ${label} shader`);
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (gl.getShaderParameter(shader, gl.COMPILE_STATUS) !== true && !gl.isContextLost()) {
    const log = gl.getShaderInfoLog(shader) ?? '';
    gl.deleteShader(shader);
    throw new Error(`glow: ${label} shader failed to compile\n${log}`);
  }
  return shader;
}

/** Compiles and links a program and looks up every active uniform once. */
export function createProgram(
  gl: WebGL2RenderingContext,
  vertexSource: string,
  fragmentSource: string,
  label: string,
): Program {
  const vs = compile(gl, gl.VERTEX_SHADER, vertexSource, `${label} vertex`);
  const fs = compile(gl, gl.FRAGMENT_SHADER, fragmentSource, `${label} fragment`);
  const program = gl.createProgram();
  gl.attachShader(program, vs);
  gl.attachShader(program, fs);
  gl.linkProgram(program);
  gl.detachShader(program, vs);
  gl.detachShader(program, fs);
  gl.deleteShader(vs);
  gl.deleteShader(fs);
  if (gl.getProgramParameter(program, gl.LINK_STATUS) !== true && !gl.isContextLost()) {
    const log = gl.getProgramInfoLog(program) ?? '';
    gl.deleteProgram(program);
    throw new Error(`glow: ${label} program failed to link\n${log}`);
  }
  const uniforms = new Map<string, WebGLUniformLocation>();
  const active = (gl.getProgramParameter(program, gl.ACTIVE_UNIFORMS) as number | null) ?? 0;
  for (let i = 0; i < active; i++) {
    const info = gl.getActiveUniform(program, i);
    if (info === null) continue;
    // Arrays report as "name[0]"; store them under the bare name.
    const name = info.name.replace(/\[0\]$/, '');
    const location = gl.getUniformLocation(program, info.name);
    if (location !== null) uniforms.set(name, location);
  }
  return { program, uniforms };
}

/** Looks up a uniform, or null when the compiler optimized it away. */
export function uniform(program: Program, name: string): WebGLUniformLocation | null {
  return program.uniforms.get(name) ?? null;
}

/** Light target storage: half-float, or 8 bits a channel for the fallback. */
export type LightFormat = 'half' | 'byte';

export interface LightTarget {
  readonly framebuffer: WebGLFramebuffer;
  readonly texture: WebGLTexture;
  /** The 8-bit fallback's fine target, drawn to at once as color attachment 1; null for half-float. */
  readonly fine: WebGLTexture | null;
  readonly width: number;
  readonly height: number;
}

/**
 * Whether this context can render and blend into RGBA16F. WebGL2 needs
 * EXT_color_buffer_float (or the half-float variant) for that, and some
 * drivers still report an incomplete framebuffer, so this also tries one.
 */
export function supportsHalfFloatTarget(gl: WebGL2RenderingContext): boolean {
  const hasExtension =
    gl.getExtension('EXT_color_buffer_float') !== null ||
    gl.getExtension('EXT_color_buffer_half_float') !== null;
  if (!hasExtension) return false;
  const probe = createLightTarget(gl, 4, 4);
  if (probe === null) return false;
  deleteLightTarget(gl, probe);
  return true;
}

function createColorTexture(
  gl: WebGL2RenderingContext,
  internalFormat: GLenum,
  width: number,
  height: number,
): WebGLTexture {
  const texture = gl.createTexture();
  gl.bindTexture(gl.TEXTURE_2D, texture);
  gl.texStorage2D(gl.TEXTURE_2D, 1, internalFormat, width, height);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  return texture;
}

/**
 * An RGBA16F color target with linear filtering and clamped edges, or for the
 * 8-bit fallback a pair of RGBA8 ones (coarse and fine) drawn to at once.
 * Null if the driver refuses it.
 */
export function createLightTarget(
  gl: WebGL2RenderingContext,
  width: number,
  height: number,
  format: LightFormat = 'half',
): LightTarget | null {
  const half = format === 'half';
  const texture = createColorTexture(gl, half ? gl.RGBA16F : gl.RGBA8, width, height);
  const fine = half ? null : createColorTexture(gl, gl.RGBA8, width, height);
  const framebuffer = gl.createFramebuffer();
  gl.bindFramebuffer(gl.FRAMEBUFFER, framebuffer);
  gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, texture, 0);
  if (fine !== null) {
    gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT1, gl.TEXTURE_2D, fine, 0);
    gl.drawBuffers([gl.COLOR_ATTACHMENT0, gl.COLOR_ATTACHMENT1]);
  }
  const complete = gl.checkFramebufferStatus(gl.FRAMEBUFFER) === gl.FRAMEBUFFER_COMPLETE;
  gl.bindFramebuffer(gl.FRAMEBUFFER, null);
  gl.bindTexture(gl.TEXTURE_2D, null);
  const target = { framebuffer, texture, fine, width, height };
  if (!complete) {
    deleteLightTarget(gl, target);
    return null;
  }
  return target;
}

export function deleteLightTarget(gl: WebGL2RenderingContext, target: LightTarget): void {
  gl.deleteFramebuffer(target.framebuffer);
  gl.deleteTexture(target.texture);
  if (target.fine !== null) gl.deleteTexture(target.fine);
}
