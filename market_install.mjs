// Offline package operation only. Never boot Cordis or execute a plugin entry.
import fs from 'node:fs';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';

const [root, profile, home, name, version, pnpm] = process.argv.slice(2);
try {
  if (!/^(?:@[a-z0-9._-]+\/)?[a-z0-9][a-z0-9._-]*$/.test(name ?? '')
      || !/^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$/.test(version ?? '')) {
    throw new Error('Invalid package identity');
  }
  const operations = await import(pathToFileURL(join(root,
    'node_modules/@deepseek-ai/dsh-plugin-manager/lib/types/operations.js')).href);
  const result = await operations.runPluginCommand({profile: 'desktop', dir: profile,
    home, cwd: profile, installAnchor: join(root, 'package.json')},
    ['add', `${name}@${version}`, '--save-exact', '--registry=https://registry.npmjs.org'], {
      execution: 'service', command: process.execPath, args: ['--expose-internals', pnpm],
      env: {ELECTRON_RUN_AS_NODE: '1', DSH_HOME: home,
        DSH_DESKTOP_NODE_EXECUTABLE: process.execPath,
        PATH: process.env.PATH,
        ...(process.env.HTTPS_PROXY ? {HTTPS_PROXY: process.env.HTTPS_PROXY} : {}),
        ...(process.env.HTTP_PROXY ? {HTTP_PROXY: process.env.HTTP_PROXY} : {}),
        ...(process.env.NO_PROXY ? {NO_PROXY: process.env.NO_PROXY} : {})},
      outputBytes: 8192, lockWaitMs: 5000, idleTimeoutMs: 120000,
      signal: AbortSignal.timeout(600000), activateNewBundles: true,
    });
  const manifestPath = join(profile, 'node_modules', name, 'package.json');
  const manifest = fs.existsSync(manifestPath) ? JSON.parse(fs.readFileSync(manifestPath, 'utf8')) : {};
  const ok = result.exitCode === 0 && !result.timedOut
    && manifest.name === name && manifest.version === version && !!manifest.dsh?.bundle;
  console.log(JSON.stringify({ok, exitCode: result.exitCode, timedOut: !!result.timedOut,
    incompatible: !!result.incompatible?.length, logPath: result.logPath,
    installedName: manifest.name, installedVersion: manifest.version}));
  if (!ok) process.exitCode = 2;
} catch (error) {
  // Diagnostic files stay local; do not return arbitrary package-manager output.
  console.log(JSON.stringify({ok: false, errorType: error?.name ?? 'Error'}));
  process.exitCode = 2;
}
