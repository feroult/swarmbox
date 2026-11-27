/* SwarmBox Shared File Viewer (used by both the slide-over Drawer in index.html
 * and the standalone fullscreen /view?path=... page).
 * Zero external dependencies, XSS-safe Markdown GFM renderer, sandboxed HTML preview,
 * folder gallery + lightbox, and code viewer with line highlight.
 */

import { encodeRawUrl, resolveRelativePath } from './viewer/utils.js';
import { detectLanguage, highlightCode, highlightLines } from './viewer/highlight.js';
import { renderMarkdown } from './viewer/markdown.js';
import { createViewer } from './viewer/controller.js';

export {
  createViewer,
  renderMarkdown,
  resolveRelativePath,
  encodeRawUrl,
  detectLanguage,
  highlightCode,
  highlightLines,
};

const api = {
  createViewer,
  renderMarkdown,
  resolveRelativePath,
  encodeRawUrl,
  detectLanguage,
  highlightCode,
  highlightLines,
};

globalThis.SwarmBoxViewer = api;
