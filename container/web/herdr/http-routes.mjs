// Web UI HTTP gateway dispatcher: origin guard, vendor assets, domain route dispatch, and static frontend serving.

import fs from 'node:fs';
import path from 'node:path';
import {
  MIME,
  PUBLIC_DIR,
  SECURITY_HEADERS,
  VENDOR_ASSETS,
  checkSameOrigin,
  detectImageFormat,
  isLoopbackAddress,
  sendJson,
  serveFile,
  validateOpenUrl,
} from './http-utils.mjs';
import { handleSystemRoutes } from './routes-system.mjs';
import { handleTabAndPinRoutes } from './routes-tabs.mjs';
import { handleWorktreeRoutes } from './routes-worktrees.mjs';

export {
  SECURITY_HEADERS,
  MIME,
  checkSameOrigin,
  isLoopbackAddress,
  validateOpenUrl,
  detectImageFormat,
};

const BUNDLED_ENTRIES = new Set(['/app.js', '/viewer.js']);

export function createHttpHandler(ctx) {
  return async (req, res) => {
    const url = new URL(req.url, `http://${req.headers.host || 'localhost'}`);
    const pathname = url.pathname;

    try {
      // Origin guard on all mutating API routes
      if (pathname.startsWith('/api/') && req.method !== 'GET' && req.method !== 'HEAD') {
        if (!checkSameOrigin(req)) {
          return sendJson(res, 403, { error: 'bad_origin', message: 'cross-origin calls are not allowed' });
        }
      }

      const vendorFile = VENDOR_ASSETS.get(pathname);
      if (vendorFile) return serveFile(res, vendorFile, true);

      if (await handleSystemRoutes(req, res, url, pathname, ctx)) return;
      if (await handleTabAndPinRoutes(req, res, url, pathname, ctx)) return;
      if (await handleWorktreeRoutes(req, res, url, pathname, ctx)) return;

      // Standalone fullscreen viewer route (/view?path=...)
      if (pathname === '/view' && (req.method === 'GET' || req.method === 'HEAD')) {
        return serveFile(res, path.join(PUBLIC_DIR, 'view.html'), false);
      }

      // Static frontend assets
      if (pathname === '/favicon.ico') return serveFile(res, path.join(PUBLIC_DIR, 'favicon.svg'), true);
      // The image bundles each ES module graph into public/dist/ (npm run build), so /app.js and /viewer.js are one
      // request each instead of one per module; a checkout without a build serves the modular source unchanged.
      if (BUNDLED_ENTRIES.has(pathname)) {
        const bundled = path.join(PUBLIC_DIR, 'dist', pathname.slice(1));
        if (fs.existsSync(bundled)) return serveFile(res, bundled, false);
      }
      const rel = pathname === '/' ? 'index.html' : pathname.replace(/^\/+/, '');
      const safePath = path.normalize(path.join(PUBLIC_DIR, rel));
      if (safePath !== PUBLIC_DIR && !safePath.startsWith(PUBLIC_DIR + path.sep)) {
        res.writeHead(403, SECURITY_HEADERS);
        return res.end('Forbidden');
      }
      return serveFile(res, safePath, false);
    } catch (err) {
      return sendJson(res, 500, { error: 'internal', message: err.message });
    }
  };
}
