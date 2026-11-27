/* Language detection and keyword/type tables for the syntax highlighter. */

export const MAX_HIGHLIGHT_CHARS = 250000;

export const LANG_ALIASES = {
  js: 'js', javascript: 'js', mjs: 'js', cjs: 'js', jsx: 'js',
  ts: 'ts', typescript: 'ts', tsx: 'ts',
  py: 'py', python: 'py',
  sh: 'sh', bash: 'sh', zsh: 'sh', shell: 'sh', console: 'sh',
  json: 'json', jsonl: 'json', jsonc: 'json',
  html: 'html', htm: 'html', xml: 'html', svg: 'html',
  css: 'css', scss: 'css', less: 'css',
  yaml: 'yaml', yml: 'yaml',
  toml: 'toml', ini: 'toml', conf: 'toml', cfg: 'toml', env: 'toml',
  go: 'go', golang: 'go',
  rs: 'rust', rust: 'rust',
  c: 'c', h: 'c', cpp: 'c', cc: 'c', cxx: 'c', hpp: 'c',
  java: 'java', kt: 'java', kotlin: 'java', cs: 'java', csharp: 'java',
  rb: 'rb', ruby: 'rb',
  php: 'php',
  sql: 'sql',
  dockerfile: 'dockerfile',
  makefile: 'makefile', mk: 'makefile',
  diff: 'diff', patch: 'diff',
  md: 'md', markdown: 'md', mdx: 'md',
};

export function normalizeLang(hint) {
  const raw = String(hint || '').trim().toLowerCase().replace(/^\./, '');
  if (!raw) return '';
  return LANG_ALIASES[raw] || '';
}

export function detectLanguage(fileNameOrLang) {
  const raw = String(fileNameOrLang || '').trim();
  if (!raw) return '';
  const direct = normalizeLang(raw);
  if (direct) return direct;
  const base = raw.split('/').pop().toLowerCase();
  if (base === 'dockerfile' || base.startsWith('dockerfile.')) return 'dockerfile';
  if (base === 'makefile' || base === 'gnumakefile') return 'makefile';
  const dot = base.lastIndexOf('.');
  if (dot > 0) {
    return normalizeLang(base.slice(dot + 1));
  }
  return '';
}

export const KW_SETS = {
  js: new Set([
    'async', 'await', 'break', 'case', 'catch', 'class', 'const', 'continue',
    'debugger', 'default', 'delete', 'do', 'else', 'export', 'extends', 'finally',
    'for', 'from', 'function', 'if', 'import', 'in', 'instanceof', 'let', 'new',
    'of', 'return', 'static', 'super', 'switch', 'this', 'throw', 'try', 'typeof',
    'var', 'void', 'while', 'with', 'yield',
  ]),
  ts: new Set([
    'abstract', 'as', 'async', 'await', 'break', 'case', 'catch', 'class', 'const',
    'continue', 'debugger', 'declare', 'default', 'delete', 'do', 'else', 'enum',
    'export', 'extends', 'finally', 'for', 'from', 'function', 'if', 'implements',
    'import', 'in', 'infer', 'instanceof', 'interface', 'is', 'keyof', 'let',
    'namespace', 'new', 'of', 'override', 'private', 'protected', 'public',
    'readonly', 'return', 'satisfies', 'static', 'super', 'switch', 'this', 'throw',
    'try', 'type', 'typeof', 'var', 'void', 'while', 'with', 'yield',
  ]),
  py: new Set([
    'and', 'as', 'assert', 'async', 'await', 'break', 'case', 'class', 'continue',
    'def', 'del', 'elif', 'else', 'except', 'finally', 'for', 'from', 'global',
    'if', 'import', 'in', 'is', 'lambda', 'match', 'nonlocal', 'not', 'or', 'pass',
    'raise', 'return', 'try', 'while', 'with', 'yield',
  ]),
  sh: new Set([
    'case', 'do', 'done', 'elif', 'else', 'esac', 'export', 'fi', 'for', 'function',
    'if', 'in', 'local', 'readonly', 'return', 'select', 'set', 'shift', 'source',
    'then', 'trap', 'unset', 'until', 'while',
  ]),
  go: new Set([
    'break', 'case', 'chan', 'const', 'continue', 'default', 'defer', 'else',
    'fallthrough', 'for', 'func', 'go', 'goto', 'if', 'import', 'interface', 'map',
    'package', 'range', 'return', 'select', 'struct', 'switch', 'type', 'var',
  ]),
  rust: new Set([
    'as', 'async', 'await', 'break', 'const', 'continue', 'crate', 'dyn', 'else',
    'enum', 'extern', 'fn', 'for', 'if', 'impl', 'in', 'let', 'loop', 'match',
    'mod', 'move', 'mut', 'pub', 'ref', 'return', 'self', 'Self', 'static',
    'struct', 'super', 'trait', 'type', 'unsafe', 'use', 'where', 'while',
  ]),
  c: new Set([
    'auto', 'break', 'case', 'catch', 'class', 'const', 'constexpr', 'continue',
    'default', 'delete', 'do', 'else', 'enum', 'explicit', 'extern', 'for', 'friend',
    'goto', 'if', 'inline', 'namespace', 'new', 'noexcept', 'operator', 'override',
    'private', 'protected', 'public', 'register', 'return', 'sizeof', 'static',
    'struct', 'switch', 'template', 'this', 'throw', 'try', 'typedef', 'typename',
    'union', 'unsigned', 'using', 'virtual', 'void', 'volatile', 'while',
  ]),
  java: new Set([
    'abstract', 'as', 'async', 'await', 'break', 'case', 'catch', 'class', 'const',
    'continue', 'data', 'default', 'do', 'else', 'enum', 'extends', 'final',
    'finally', 'for', 'fun', 'if', 'implements', 'import', 'in', 'interface',
    'internal', 'is', 'namespace', 'new', 'object', 'open', 'override', 'package',
    'private', 'protected', 'public', 'readonly', 'record', 'return', 'sealed',
    'static', 'super', 'switch', 'this', 'throw', 'throws', 'try', 'using', 'val',
    'var', 'virtual', 'void', 'when', 'while',
  ]),
  rb: new Set([
    'alias', 'and', 'begin', 'break', 'case', 'class', 'def', 'defined?', 'do',
    'else', 'elsif', 'end', 'ensure', 'for', 'if', 'in', 'module', 'next', 'not',
    'or', 'redo', 'rescue', 'retry', 'return', 'self', 'super', 'then', 'undef',
    'unless', 'until', 'when', 'while', 'yield', 'require', 'require_relative',
  ]),
  php: new Set([
    'abstract', 'and', 'array', 'as', 'break', 'callable', 'case', 'catch', 'class',
    'clone', 'const', 'continue', 'declare', 'default', 'do', 'echo', 'else',
    'elseif', 'empty', 'extends', 'final', 'finally', 'fn', 'for', 'foreach',
    'function', 'global', 'if', 'implements', 'include', 'include_once', 'instanceof',
    'interface', 'isset', 'match', 'namespace', 'new', 'or', 'private', 'protected',
    'public', 'readonly', 'require', 'require_once', 'return', 'static', 'switch',
    'throw', 'trait', 'try', 'unset', 'use', 'var', 'while', 'yield',
  ]),
  sql: new Set([
    'select', 'from', 'where', 'join', 'left', 'right', 'inner', 'outer', 'full',
    'cross', 'on', 'as', 'and', 'or', 'not', 'in', 'is', 'null', 'like', 'ilike',
    'between', 'exists', 'case', 'when', 'then', 'else', 'end', 'group', 'by',
    'having', 'order', 'asc', 'desc', 'limit', 'offset', 'union', 'all', 'distinct',
    'insert', 'into', 'values', 'update', 'set', 'delete', 'create', 'alter', 'drop',
    'table', 'index', 'view', 'primary', 'key', 'foreign', 'references', 'constraint',
    'default', 'unique', 'check', 'with', 'recursive', 'returning', 'begin', 'commit',
    'rollback', 'transaction', 'explain', 'analyze',
  ]),
  dockerfile: new Set([
    'from', 'run', 'cmd', 'label', 'maintainer', 'expose', 'env', 'add', 'copy',
    'entrypoint', 'volume', 'user', 'workdir', 'arg', 'onbuild', 'stopsignal',
    'healthcheck', 'shell', 'as',
  ]),
};

export const BOOL_WORDS = new Set([
  'true', 'false', 'null', 'undefined', 'nil', 'none', 'True', 'False', 'None',
  'NaN', 'Infinity', 'Some', 'Ok', 'Err',
]);

export const BUILTIN_TYPES = new Set([
  'string', 'number', 'boolean', 'any', 'unknown', 'never', 'object', 'symbol', 'bigint',
  'int', 'int8', 'int16', 'int32', 'int64', 'uint', 'uint8', 'uint16', 'uint32', 'uint64',
  'float', 'float32', 'float64', 'double', 'char', 'byte', 'rune', 'bool', 'str', 'bytes',
  'usize', 'isize', 'i8', 'i16', 'i32', 'i64', 'u8', 'u16', 'u32', 'u64', 'f32', 'f64',
  'size_t', 'error', 'void',
]);
