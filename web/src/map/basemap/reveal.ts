/**
 * The map canvas stays hidden until its first complete frame is ready, while
 * the inline still shows the same lines. That keeps half-loaded frames off
 * screen, and the compositor never waits on the GPU for them: on a slow or
 * software GPU a composited WebGL canvas makes the main thread wait for every
 * frame it shows.
 */

/** Class on the map container once the canvas may be composited. */
export const LIVE_CLASS = 'is-live';

const POLL_MS = 16;

/**
 * Resolves once the GPU has finished everything submitted so far, polled with
 * a fence so the main thread never blocks on it. Gives up after `timeoutMs`.
 */
export function whenGpuIdle(gl: WebGL2RenderingContext, timeoutMs = 3000): Promise<void> {
  const sync = gl.fenceSync(gl.SYNC_GPU_COMMANDS_COMPLETE, 0);
  if (sync === null) return Promise.resolve();
  gl.flush();
  const start = performance.now();
  return new Promise((resolve) => {
    const poll = (): void => {
      const done =
        gl.isContextLost() ||
        gl.getSyncParameter(sync, gl.SYNC_STATUS) === gl.SIGNALED ||
        performance.now() - start > timeoutMs;
      if (!done) {
        setTimeout(poll, POLL_MS);
        return;
      }
      if (!gl.isContextLost()) gl.deleteSync(sync);
      resolve();
    };
    setTimeout(poll, 0);
  });
}

/** Resolves on the next task after the next frame, once that frame has been painted. */
export function afterNextFrame(): Promise<void> {
  return new Promise((resolve) => {
    requestAnimationFrame(() => {
      setTimeout(resolve, 0);
    });
  });
}
