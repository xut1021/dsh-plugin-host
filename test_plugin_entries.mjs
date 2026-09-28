import test from 'node:test';
import assert from 'node:assert/strict';
import {bundleEntryInfo, effectiveEntryStates} from './plugin_entries.mjs';

test('toggles owned roots while identifying nested plugin entries', () => {
  const result = bundleEntryInfo([{insert:[{id:'group',group:true,config:[{id:'feature',disabled:true},
    {id:'nested',config:{plugins:[{id:'deep'}]}}]}]}, {id:'existing-group',insert:[{id:'another'}]}]);
  assert.deepEqual(result.entry_ids, ['group','another']);
  assert.deepEqual(result.nested_entry_ids, ['group','feature','nested','deep','another']);
  assert.equal(result.complete, true);
});

test('unidentified and duplicate roots do not offer a toggle', () => {
  assert.equal(bundleEntryInfo([{insert:[{id:'known'}, {name:'unnamed'}]}]).complete, false);
  assert.equal(bundleEntryInfo([{insert:[{id:'same'}, {id:'same'}]}]).complete, false);
  assert.equal(bundleEntryInfo([]).complete, false);
  assert.equal(bundleEntryInfo([{insert:[{id:'conditional',disabled:{__jsExpr:'condition'}}]}]).states.get('conditional').enabled, null);
});

test('effective state respects disabled ancestors and does not expose dynamic expressions', () => {
  const states = effectiveEntryStates([{id:'group',group:true,disabled:true,config:[{id:'child'}]},
    {id:'conditional', disabled:{__jsExpr:'DO NOT SERIALIZE THIS EXPRESSION'}}, {id:'normal'}]);
  assert.equal(states.get('child').enabled, false);
  assert.equal(states.get('child').ancestor_disabled, true);
  assert.equal(states.get('conditional').enabled, null);
  assert.equal(states.get('conditional').conditional, true);
  assert.equal(states.get('normal').enabled, true);
  assert.ok(!JSON.stringify([...states]).includes('DO NOT SERIALIZE'));
});
