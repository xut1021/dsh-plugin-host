// Prepare only disabled-flag edits. Do not boot plugins or print profile values.
import fs from 'node:fs';
import crypto from 'node:crypto';
import { join } from 'node:path';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
const [root, profile] = process.argv.slice(2);
try {
  const changes = JSON.parse(fs.readFileSync(0, 'utf8'));
  const require = createRequire(join(root, 'package.json'));
  const YAML = require('yaml');
  const yaml = require('js-yaml');
  const include = await import(pathToFileURL(require.resolve('@deepseek-ai/cordis-plugin-include')));
  const boot = await import(pathToFileURL(join(root, 'node_modules/@deepseek-ai/dsh-app-boot/lib/index.js')));
  const loaded = boot.loadProfileDirectory('dsh', profile, join(root, 'package.json'));
  const manifest = JSON.parse(fs.readFileSync(join(profile, 'package.json'), 'utf8'));
  const bundles = manifest.dsh?.profile?.bundles ?? [];
  const roots = new Map(), owners = new Map();
  for (const name of bundles) {
    let patches = loaded.layers.find(layer => layer.packageName === name)?.patches;
    if (!patches) {
      try {
        const dir = join(profile, 'node_modules', name);
        const meta = JSON.parse(fs.readFileSync(join(dir, 'package.json'), 'utf8'));
        patches = boot.bundlePatchPaths(dir, meta.dsh.bundle).flatMap(p => boot.loadOverlayPatches('dsh', p));
      } catch { continue; }
    }
    const rows = patches.flatMap(p => p.insert ?? []);
    roots.set(name, rows);
    for (const row of rows) {
      if (typeof row.id !== 'string') continue;
      const set = owners.get(row.id) ?? new Set();
      set.add(name); owners.set(row.id, set);
    }
  }
  const flags = new Map();
  for (const [name, enabled] of Object.entries(changes)) {
    if (typeof enabled !== 'boolean' || name.startsWith('@deepseek-ai/') || !Object.hasOwn(manifest.dependencies ?? {}, name))
      throw new Error('unsupported-plugin');
    const rows = roots.get(name);
    if (!bundles.includes(name) || !rows?.length || rows.some(row => typeof row.id !== 'string' || owners.get(row.id)?.size !== 1))
      throw new Error('ambiguous-plugin-entries');
    for (const row of rows) flags.set(row.id, !enabled);
  }
  const patchPath = join(profile, 'cordis.patch.yml');
  const exists = fs.existsSync(patchPath);
  const original = exists ? fs.readFileSync(patchPath, 'utf8') : '[]\n';
  const doc = YAML.parseDocument(original, { keepSourceTokens: true,
    customTags: [{ tag:'tag:yaml.org,2002:js', resolve:value => ({ __jsExpr:value }) }] });
  if (doc.errors.length || !YAML.isSeq(doc.contents)) throw new Error('unsupported-patch-document');
  const edits = [], append = [];
  for (const [id, disabled] of flags) {
    const row = [...doc.contents.items].reverse().find(item => YAML.isMap(item) && item.get('id') === id && item.has('disabled'));
    const node = row?.get('disabled', true);
    if (YAML.isScalar(node) && typeof node.value === 'boolean' && !node.tag) {
      edits.push({ start:node.range[0], end:node.range[1], value:String(disabled) });
    } else append.push({ id, disabled });
  }
  if (append.length) {
    if (doc.contents.flow) {
      const close = doc.contents.range[1] - 1;
      if (original[close] !== ']') throw new Error('unsupported-flow-patch');
      const value = (doc.contents.items.length ? ',' : '') + '\n' + append.map(row =>
        `  { id: ${JSON.stringify(row.id)}, disabled: ${row.disabled} }`).join(',\n') + '\n';
      edits.push({ start:close, end:close, value });
    } else {
      const end = doc.contents.range[1];
      const value = (original[end-1] === '\n' ? '' : '\n') + append.map(row =>
        `- id: ${JSON.stringify(row.id)}\n  disabled: ${row.disabled}\n`).join('');
      edits.push({ start:end, end, value });
    }
  }
  let candidate = original;
  for (const edit of edits.sort((a,b) => b.start-a.start))
    candidate = candidate.slice(0,edit.start) + edit.value + candidate.slice(edit.end);
  const patches = yaml.load(candidate, { schema:include.entryListSchema });
  if (!Array.isArray(patches)) throw new Error('invalid-patch-result');
  const baseLayers = loaded.layers.map(layer => layer.patches);
  const before = boot.composeEntries([...baseLayers, loaded.patches]);
  const after = boot.composeEntries([...baseLayers, patches]);
  const expected = structuredClone(before);
  const found = new Map();
  function visit(rows, mutate = false, ancestorDisabled = false) {
    for (const row of rows) {
      if (mutate && flags.has(row.id)) row.disabled = flags.get(row.id);
      const disabled = ancestorDisabled || row.disabled === true || !!row.disabled && typeof row.disabled !== 'boolean';
      if (!mutate && flags.has(row.id)) found.set(row.id, !disabled);
      if (row.group && Array.isArray(row.config)) visit(row.config, mutate, disabled);
    }
  }
  visit(expected, true); visit(after);
  if (JSON.stringify(expected) !== JSON.stringify(after)) throw new Error('unrelated-config-change');
  for (const [id, disabled] of flags) {
    // Skipped incompatible bundles may still be disabled for the next supported runtime.
    if (!disabled && found.get(id) !== true || disabled && found.has(id) && found.get(id) !== false)
      throw new Error('effective-state-not-changed');
  }
  console.log(JSON.stringify({ content_base64:Buffer.from(candidate).toString('base64'),
    original_sha256:exists ? crypto.createHash('sha256').update(fs.readFileSync(patchPath)).digest('hex') : null,
    entry_ids:[...flags.keys()] }));
} catch (error) {
  const safe = ['unsupported-plugin','ambiguous-plugin-entries','unsupported-patch-document',
    'unsupported-flow-patch','invalid-patch-result','unrelated-config-change','effective-state-not-changed'];
  console.log(JSON.stringify({ error:safe.includes(error?.message) ? error.message : 'toggle-patch-inspection-failed' }));
  process.exitCode = 2;
}
