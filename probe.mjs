// Read the installed DSH loader's own compatibility decision. Never boot plugins.
import fs from 'node:fs';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { sourceReportFields } from './source_metadata.mjs';
import { bundleEntryInfo, effectiveEntryStates, entryChildren } from './plugin_entries.mjs';
const [root, profile] = process.argv.slice(2);
try {
  const boot = await import(pathToFileURL(join(root, 'node_modules/@deepseek-ai/dsh-app-boot/lib/index.js')).href);
  const result = boot.loadProfileDirectory('dsh', profile, join(root, 'package.json'));
  const manifest = JSON.parse(fs.readFileSync(join(profile, 'package.json'), 'utf8'));
  const runtime = boot.getDshRuntimeVersion();
  const exemptions = boot.readProfileVersionExemptions?.(profile) ?? {};
  const disabled = new Map();
  function rows(items) {
    for (const row of items ?? []) {
      if (row.id && typeof row.disabled === 'boolean') disabled.set(row.id, row.disabled);
      rows(entryChildren(row));
    }
  }
  rows(result.patches);
  let effective = new Map();
  try { effective = effectiveEntryStates(boot.composeEntries([...result.layers.map(l => l.patches), result.patches])); } catch {}
  const plugins = [];
  function exportFile(value) {
    if (typeof value === 'string') return value;
    if (value && typeof value === 'object') return exportFile(value.default ?? value.import ?? value.browser);
  }
  for (const [name, requested] of Object.entries(manifest.dependencies ?? {})) {
    if (name.startsWith('@deepseek-ai/')) continue;
    const dir = join(profile, 'node_modules', name);
    let meta;
    try { meta = JSON.parse(fs.readFileSync(join(dir, 'package.json'), 'utf8')); }
    catch { plugins.push({name, ...sourceReportFields(requested), status:'missing', enabled:null,
      enabled_state:'unknown', entry_ids:[], nested_entry_ids:[], toggle_supported:false, toggle_reason:'插件尚未安装'}); continue; }
    const issue = boot.evaluatePluginCompatibility?.(meta, exemptions, runtime);
    const skipped = result.skippedBundles.find(x => x.packageName === name);
    const layer = result.layers.find(x => x.packageName === name);
    let bundlePatches=layer?.patches ?? [];
    if (!layer && meta.dsh?.bundle) {
      try { bundlePatches=boot.bundlePatchPaths(dir,meta.dsh.bundle).flatMap(p=>boot.loadOverlayPatches('dsh',p)); } catch {}
    }
    const entries = bundleEntryInfo(bundlePatches);
    const ids = entries.entry_ids;
    const bundled = (manifest.dsh?.profile?.bundles ?? []).includes(name);
    const effectiveRows = layer ? ids.map(id => effective.get(id)) : [];
    const haveEffectiveRows = effectiveRows.length > 0 && effectiveRows.every(Boolean);
    const enabledValues = haveEffectiveRows ? effectiveRows.map(row => row.enabled)
      : ids.map(id => disabled.has(id) ? !disabled.get(id) : entries.states.get(id)?.enabled ?? null);
    const enabledState = !enabledValues.length ? 'unknown' : enabledValues.some(value => value === null) ? 'conditional'
      : enabledValues.every(Boolean) ? 'enabled' : enabledValues.every(value => value === false) ? 'disabled' : 'mixed';
    let toggleReason = !bundled ? '插件未加入当前配置的加载清单' : !entries.complete ? '无法完整识别插件入口'
      : layer && !haveEffectiveRows ? '无法确认组合配置中的插件入口'
      : enabledState === 'conditional' ? '启用状态由动态表达式控制'
      : effectiveRows.some(row => row?.ancestor_disabled) ? '上层分组已禁用，无法单独切换' : '';
    let client = '';
    try { client = fs.readFileSync(join(dir, exportFile(meta.exports?.['./client']) ?? 'lib/client.js'), 'utf8'); } catch {}
    // Literal-only dependency hints. They are not a proof of successful activation.
    const provides = [...client.matchAll(/\.provide\(\s*["']([\w-]+)["']/g)].map(m => m[1]);
    const needs = [...client.matchAll(/(?:\binject\s*[:=])\s*\[([^\]]*)\]/g)]
      .flatMap(m => [...m[1].matchAll(/["']([\w-]+)["']/g)].map(x => x[1]));
    plugins.push({name, ...sourceReportFields(requested,meta), version:meta.version,
      enabled:enabledState === 'conditional' || enabledState === 'unknown' ? null : enabledState !== 'disabled',
      enabled_state:enabledState, enabled_evidence:haveEffectiveRows ? 'composed-entry-flags' : 'bundle-and-profile-overlay-flags',
      entry_ids:ids, nested_entry_ids:entries.nested_entry_ids, toggle_supported:!toggleReason, toggle_reason:toggleReason,
      bundled,
      status:skipped ? (issue && !issue.exempted ? 'version-blocked':'loader-skipped') : 'metadata-ok',
      peers:issue?.peers ?? {}, exempted:issue?.exempted ?? false,
      reason:skipped?.reason, provides:[...new Set(provides)], needs:[...new Set(needs)],
      declaredDependencies:meta.dsh?.client?.inject ?? [], functionality:'unverified'});
  }
  const owners = new Map();
  for (const plugin of plugins) {
    for (const id of plugin.nested_entry_ids) {
      if (!owners.has(id)) owners.set(id, new Set());
      owners.get(id).add(plugin.name);
    }
  }
  for (const plugin of plugins) {
    if (plugin.entry_ids.some(id => owners.get(id)?.size > 1)) {
      plugin.toggle_supported = false;
      plugin.toggle_reason = '插件入口与其他插件重名，无法安全切换';
    }
  }
  const blocked = new Map(plugins.filter(p => p.status !== 'metadata-ok').map(p => [p.name,p]));
  let changed = true;
  while (changed) {
    changed = false;
    for (const p of plugins) {
      if (blocked.has(p.name) || p.enabled === false) continue;
      const dependencies = [];
      for (const q of plugins) {
        if (!blocked.has(q.name)) continue;
        const services = (p.needs ?? []).filter(s => (q.provides ?? []).includes(s));
        if (services.length || (p.declaredDependencies ?? []).includes(q.name)) dependencies.push({plugin:q.name, services});
      }
      if (dependencies.length) {
        p.status='dependency-blocked'; p.blockedBy=dependencies;
        p.evidence='literal dependency hint; confirm with runtime diagnostics';
        blocked.set(p.name,p); changed=true;
      }
    }
  }
  console.log(JSON.stringify({runtime, compatibilityApi:typeof boot.evaluatePluginCompatibility === 'function', plugins, skipped:result.skippedBundles.map(x=>x.packageName),
    layers:result.layers.map(x=>x.packageName), functionality:'unverified'}));
} catch (error) {
  // Do not serialize configuration fragments or plugin exception objects.
  console.log(JSON.stringify({error:'DSH loader probe failed', errorType:error?.name ?? 'Error'}));
  process.exitCode=2;
}
