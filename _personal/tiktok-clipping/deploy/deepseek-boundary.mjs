/** Deny tool execution in the untrusted-content analysis process. */
export const name = 'tiktok-clipping-analysis-boundary';
export const inject = ['tools'];

export function apply(ctx) {
  if (typeof ctx.tools?.guard !== 'function') {
    throw new Error('Clipping analysis requires the deterministic tool guard.');
  }
  ctx.tools.guard(() => 'Tool execution is disabled for clipping analysis.');
}
