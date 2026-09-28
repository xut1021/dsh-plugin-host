// Installation provenance and an upstream repository are different facts.
// Read only manifest values; never inspect Git configuration or credentials.
const labels = {local:'本地', github:'GitHub', git:'Git', npm:'npm', url:'下载链接', unknown:'来源不明'};
const controls = /[\u0000-\u001f\u007f]/;

function webUrl(value, repository = false) {
  if (typeof value !== 'string' || controls.test(value)) return undefined;
  let text = value.trim().replace(/^git\+/, '');
  if (repository) {
    const shortcut = text.match(/^(?:github:)?([\w.-]+)\/([\w.-]+)(?:#.*)?$/);
    if (shortcut) text = `https://github.com/${shortcut[1]}/${shortcut[2]}`;
    const scp = text.match(/^git@([\w.-]+):([^\s?#]+)(?:[?#].*)?$/);
    if (scp) text = `https://${scp[1]}/${scp[2]}`;
  }
  let url;
  try { url = new URL(text); } catch { return undefined; }
  if (repository && ['ssh:', 'git:'].includes(url.protocol)) {
    // Reparse: URL does not allow switching a non-special scheme to https.
    try { url = new URL(`https://${url.hostname}${url.pathname}`); } catch { return undefined; }
  }
  if (!['https:', 'http:'].includes(url.protocol) || !url.hostname) return undefined;
  url.username = ''; url.password = ''; url.search = ''; url.hash = '';
  if (['github.com', 'gitlab.com', 'bitbucket.org'].includes(url.hostname)) url.protocol = 'https:';
  if (repository) url.pathname = url.pathname.replace(/\.git\/?$/, '');
  return url.href.replace(/\/$/, '');
}

export function sanitizeRepositoryUrl(value) {
  return webUrl(typeof value === 'object' && value !== null ? value.url : value, true);
}

function classify(value) {
  if (typeof value !== 'string' || !value.trim() || controls.test(value)) return undefined;
  const text = value.trim();
  if (/^(?:file:|link:|workspace:|\.\.?[\\/]|[\\/]|[A-Za-z]:[\\/])/.test(text)) {
    // Paths may contain # or ? as names; only file URLs have URL credentials.
    if (/^file:\/\//i.test(text)) {
      try {
        const url = new URL(text);
        if (url.username || url.password) return {kind:'local', location:'本地文件'};
        url.search = ''; url.hash = '';
        return {kind:'local', location:url.href};
      } catch { return {kind:'local', location:'本地文件'}; }
    }
    return {kind:'local', location:text};
  }
  if (/^(?:github:|[\w.-]+\/[\w.-]+(?:#|$))/.test(text)) {
    const location = sanitizeRepositoryUrl(text);
    if (location) return {kind:'github', location};
  }
  if (/^(?:git(?:\+|:|@)|ssh:)/.test(text)) {
    const location = sanitizeRepositoryUrl(text);
    if (location) return {kind:new URL(location).hostname === 'github.com' ? 'github' : 'git', location};
  }
  if (/^https?:/i.test(text)) {
    const location = webUrl(text);
    if (location) {
      const url = new URL(location);
      const kind = url.hostname === 'github.com' ? 'github'
        : url.hostname === 'registry.npmjs.org' ? 'npm'
        : /\.git\/?$/.test(url.pathname) ? 'git' : 'url';
      return {kind, location};
    }
  }
  if (/^npm:(?:@[\w.-]+\/)?[\w.-]+(?:@[\w.*~^<>=| +\-]+)?$/.test(text)
      || /^[\w.*~^<>=| +\-]+$/.test(text)) return {kind:'npm', location:text};
  return undefined;
}

export function sourceMetadata(requested, meta = {}) {
  let source = classify(requested);
  let evidence = 'profile.package.json dependencies';
  // _resolved is only a fallback when no declared install request is available.
  if (!source && (requested === undefined || requested === null || requested === '')) {
    source = classify(meta._resolved);
    evidence = '插件 package.json _resolved';
  }
  source ??= {kind:'unknown', location:'未识别的安装声明'};
  const repositoryUrl = sanitizeRepositoryUrl(meta.repository);
  const homepage = repositoryUrl ? undefined : webUrl(meta.homepage, true);
  // A homepage is only a repository link if it points to a known code host.
  const upstream = repositoryUrl ?? (homepage && ['github.com', 'gitlab.com', 'bitbucket.org'].includes(new URL(homepage).hostname) ? homepage : undefined);
  return {...source, label:labels[source.kind], evidence,
    ...(upstream ? {repository_url:upstream,
      repository_evidence:repositoryUrl ? '插件 package.json repository' : '插件 package.json homepage'} : {})};
}

export function sourceReportFields(requested, meta = {}) {
  const source = sourceMetadata(requested, meta);
  // Keep the original declaration only in the loader input, never in a report:
  // it can contain authenticated Git URLs even when the source card is safe.
  return {requested:source.location, source};
}
