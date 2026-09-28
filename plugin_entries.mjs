// Keep child feature choices intact: toggles target owned inserted roots only.
export function entryChildren(row) {
  return [row?.insert, row?.config?.plugins, row?.group ? row.config : undefined]
    .filter(Array.isArray).flat();
}

export function bundleEntryInfo(patches) {
  const roots = (patches ?? []).flatMap(p => Array.isArray(p.insert) ? p.insert : []);
  const identified = row => typeof row?.id === 'string' && !!row.id.trim() && !/[\u0000-\u001f\u007f]/.test(row.id);
  const entry_ids = roots.filter(identified).map(row => row.id);
  const nested = [];
  function visit(rows) {
    for (const row of rows) {
      if (identified(row)) nested.push(row.id);
      visit(entryChildren(row));
    }
  }
  visit(roots);
  return {entry_ids:[...new Set(entry_ids)], nested_entry_ids:[...new Set(nested)],
    states:effectiveEntryStates(roots),
    complete:roots.length > 0 && roots.every(identified) && entry_ids.length === new Set(entry_ids).size};
}

export function effectiveEntryStates(entries) {
  const states = new Map();
  function visit(rows, ancestorDisabled = false, ancestorConditional = false) {
    for (const row of rows ?? []) {
      const ownConditional = row.disabled !== undefined && typeof row.disabled !== 'boolean';
      const disabled = ancestorDisabled || row.disabled === true;
      const conditional = !disabled && (ancestorConditional || ownConditional);
      if (typeof row.id === 'string') states.set(row.id, {enabled:conditional ? null : !disabled,
        ancestor_disabled:ancestorDisabled, conditional});
      visit(entryChildren(row), disabled, conditional);
    }
  }
  visit(entries);
  return states;
}
