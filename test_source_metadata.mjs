import test from 'node:test';
import assert from 'node:assert/strict';
import {sourceMetadata, sourceReportFields, sanitizeRepositoryUrl} from './source_metadata.mjs';

test('local installation remains local even with declared GitHub upstream', () => {
  const source = sourceMetadata('file:../../plugins/sidebar', {repository:{type:'git',url:'git+https://github.com/owner/sidebar.git'}});
  assert.equal(source.kind, 'local');
  assert.equal(source.location, 'file:../../plugins/sidebar');
  assert.equal(source.repository_url, 'https://github.com/owner/sidebar');
  for (const spec of ['link:../plugin', 'workspace:*', '../plugin', './plugin', '/tmp/plugin', 'C:\\plugins\\sidebar']) {
    assert.equal(sourceMetadata(spec).kind, 'local', spec);
  }
});

test('classifies declared npm, GitHub, Git and download sources', () => {
  for (const spec of ['1.2.3', '^1.0.0', '~0.2', '*', 'latest', '>=1.0.0 <2', 'npm:@scope/plugin@^2.0.0', 'npm:plugin@beta']) {
    assert.equal(sourceMetadata(spec).kind, 'npm', spec);
  }
  for (const spec of ['github:owner/plugin#main', 'owner/plugin#v1', 'git+https://github.com/owner/plugin.git#main', 'git@github.com:owner/plugin.git', 'git+ssh://git@github.com/owner/plugin.git']) {
    assert.equal(sourceMetadata(spec).kind, 'github', spec);
  }
  assert.equal(sourceMetadata('git+https://gitlab.com/owner/plugin.git').kind, 'git');
  assert.equal(sourceMetadata('https://example.org/plugin.tgz').kind, 'url');
  assert.equal(sourceMetadata('https://example.org/plugin.git').kind, 'git');
  assert.equal(sourceMetadata('https://registry.npmjs.org/plugin/-/plugin-1.0.0.tgz').kind, 'npm');
});

test('removes credential, query and fragment values from every returned URL', () => {
  const source = sourceMetadata('git+https://user:secret@github.com/owner/plugin.git?token=private#secret', {
    repository:'https://another:password@gitlab.com/owner/plugin.git?auth=secret#private'
  });
  assert.equal(source.location, 'https://github.com/owner/plugin');
  assert.equal(source.repository_url, 'https://gitlab.com/owner/plugin');
  for (const secret of ['secret', 'password', 'private', 'another']) assert.ok(!JSON.stringify(source).includes(secret));
  assert.equal(sourceMetadata('https://u:secret@example.org/archive.tgz?token=private#private').location, 'https://example.org/archive.tgz');
  assert.equal(sanitizeRepositoryUrl('git+ssh://git:secret@gitlab.com:22/owner/plugin.git?token=x#main'), 'https://gitlab.com/owner/plugin');
});

test('rejects executable links, malformed declarations, and control characters', () => {
  for (const repository of ['javascript:alert(1)', 'data:text/html,secret', 'file:///C:/secret', 'https://github.com/owner\n/secret', 'not a URL']) {
    assert.equal(sourceMetadata('*', {repository}).repository_url, undefined, repository);
  }
  assert.equal(sourceMetadata('javascript:alert(1)', {repository:'https://github.com/owner/plugin'}).kind, 'unknown');
  assert.equal(sourceMetadata('unknown://u:password@example.org?token=secret').location, '未识别的安装声明');
  assert.equal(sourceMetadata('*', {homepage:'https://example.org/docs'}).repository_url, undefined);
});

test('missing installed package uses declared source; no provenance guesses from name or upstream', () => {
  assert.equal(sourceMetadata('github:owner/missing').kind, 'github');
  assert.equal(sourceMetadata('file:../missing').kind, 'local');
  assert.equal(sourceMetadata(undefined, {name:'github-plugin', repository:'https://github.com/owner/plugin'}).kind, 'unknown');
  assert.equal(sourceMetadata(undefined, {_resolved:'https://registry.npmjs.org/plugin/-/plugin.tgz'}).kind, 'npm');
  assert.equal(sourceMetadata('^2', {_resolved:'file:../plugin'}).kind, 'npm');
});

test('report requested field cannot reintroduce authenticated URL declarations', () => {
  for (const declaration of ['git+https://user:secret@github.com/owner/plugin.git?token=private#secret',
      'https://user:secret@registry.npmjs.org/plugin.tgz?token=private',
      'unknown://user:secret@example.org?token=private']) {
    const fields = sourceReportFields(declaration);
    assert.equal(fields.requested, fields.source.location);
    for (const secret of ['secret', 'private']) assert.ok(!JSON.stringify(fields).includes(secret));
  }
  assert.equal(sourceReportFields('file:../plugin').requested, 'file:../plugin');
  assert.equal(sourceReportFields('^1.2.3').requested, '^1.2.3');
});
