"""Offline documentation and AST comparison."""
import argparse
import ast
import json
import os
from pathlib import Path
import re
import sys
from .phrases import VAD, NOVAD


def normalize(text):
    return ' '.join(text.lower().replace("n't", ' not').replace('-', ' ').split())


def phrases(text, vocabulary):
    found = []
    for phrase in sorted(vocabulary, key=lambda x: (-len(x), x)):
        pattern = r'\b' + re.escape(phrase) + r'\b'
        if re.search(pattern, text):
            found.append(phrase)
            text = re.sub(pattern, lambda m: ' ' * len(m.group()), text)
    return found, text


def claims(text):
    lines = []
    fence = None
    for line in text.splitlines():
        match = re.match(r'^ {0,3}(`{3,}|~{3,})(.*)$', line)
        if fence:
            if match and match[1][0] == fence[0] and len(match[1]) >= len(fence) and not match[2].strip():
                fence = None
            continue
        if match:
            fence = match[1]
            continue
        lines.append(line)
    positive, negative = [], []
    for paragraph in re.split(r'\n\s*\n', '\n'.join(lines)):
        denied, rest = phrases(normalize(paragraph), NOVAD)
        asserted, _ = phrases(rest, VAD)
        positive.extend(asserted)
        negative.extend(denied)
    return positive, negative


def evidence(source):
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return False
    aliases = {}
    shadow = set()
    func_shadow = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            func_shadow.add(node.name)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            shadow.add(node.name)
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            shadow.add(node.id)
        if isinstance(node, ast.arg):
            shadow.add(node.arg)
        if isinstance(node, ast.Import):
            for item in node.names:
                aliases[item.asname or item.name.split('.')[0]] = item.name if item.asname else item.name.split('.')[0]
        if isinstance(node, ast.ImportFrom):
            for item in node.names:
                aliases[item.asname or item.name] = (node.module or '') + '.' + item.name
    def resolve(node):
        if isinstance(node, ast.Name):
            return '' if node.id in shadow else aliases.get(node.id, '')
        if isinstance(node, ast.Attribute):
            base = resolve(node.value)
            return base + '.' + node.attr if base else ''
        return ''
    web = any(v == 'webrtcvad' or v.startswith('webrtcvad.') for v in aliases.values())
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        attr = func.attr if isinstance(func, ast.Attribute) else ''
        if attr in ('is_speech', 'get_speech_timestamps', 'get_speech_segments') and attr not in func_shadow:
            base = func.value
            while isinstance(base, ast.Attribute):
                base = base.value
            if isinstance(base, ast.Name) and base.id in shadow and base.id in aliases:
                continue
            if attr != 'is_speech' or web:
                return True
        if isinstance(func, ast.Name) and func.id not in shadow and (func.id == 'get_speech_timestamps' or resolve(func).endswith('.get_speech_timestamps')):
            return True
        name = resolve(func)
        if name.startswith('inaSpeechSegmenter.') and name.endswith('.Segmenter'):
            return True
        if name.startswith('pyannote.') and name.endswith('.Pipeline.from_pretrained'):
            args = list(node.args) + [k.value for k in node.keywords]
            if any(isinstance(a, ast.Constant) and isinstance(a.value, str) and 'segmentation' in a.value.lower() for a in args):
                return True
    return False


def audit(root, ignore=()):
    root = Path(root)
    if not root.is_dir() or root.is_symlink():
        raise OSError('root must be a readable directory')
    positives, negatives, production, tests = [], [], [], []
    ignored = [Path(i).as_posix().strip('/') for i in ignore]
    def skip(rel):
        return any(rel == i or rel.startswith(i + '/') for i in ignored)
    for base, dirs, files in os.walk(root, onerror=lambda error: (_ for _ in ()).throw(error)):
        dirs[:] = sorted(d for d in dirs if not (Path(base)/d).is_symlink() and not skip((Path(base)/d).relative_to(root).as_posix()))
        for filename in sorted(files):
            path = Path(base)/filename
            rel = path.relative_to(root)
            if path.is_symlink() or skip(rel.as_posix()):
                continue
            if rel.as_posix() == 'README.md' or (path.suffix == '.md' and 'docs' in rel.parts[:-1]):
                pos, neg = claims(path.read_text(encoding='utf-8'))
                positives.extend(pos)
                negatives.extend(neg)
            if path.suffix != '.py' or set(rel.parts[:-1]) & {'fixtures', 'docs', 'examples'}:
                continue
            is_test = 'tests' in rel.parts[:-1] or filename.startswith('test_') or filename.endswith('_test.py')
            if evidence(path.read_text(encoding='utf-8')):
                (tests if is_test else production).append(rel.as_posix())
    findings = []
    if positives and not production:
        severity = 'MEDIUM' if tests else 'HIGH'
        findings.append(dict(rule_id='documented-voice-activity-detection-claim-false', severity=severity, message='Documented claim has evidence only in tests.' if tests else 'Documented claim lacks production source evidence.'))
    if negatives and production:
        findings.append(dict(rule_id='documented-no-voice-activity-detection-claim-false', severity='HIGH', message='Documented denial conflicts with production source evidence.'))
    return dict(verdict='FAIL' if findings else 'PASS', findings=findings, production_evidence=production, test_evidence=tests)


class Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(1, self.prog + ': error: ' + message + '\n')


def main(argv=None):
    parser = Parser(description='Compare documentation claims with Python source fingerprints.')
    parser.add_argument('root', nargs='?', default='.')
    parser.add_argument('--version', action='version', version='0.1.0')
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--verbose', action='store_true')
    parser.add_argument('--ignore', action='append', default=[])
    parser.add_argument('--fail-on', choices=['LOW', 'MEDIUM', 'HIGH'], default='HIGH')
    args = parser.parse_args(argv)
    try:
        result = audit(args.root, args.ignore)
    except (OSError, UnicodeError) as error:
        print(str(error), file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        print(result['verdict'])
        for finding in result['findings']:
            print('{severity} {rule_id}: {message}'.format(**finding))
        if args.verbose:
            print('Production evidence: ' + ', '.join(result['production_evidence']))
            print('Test evidence: ' + ', '.join(result['test_evidence']))
    rank = {'LOW': 0, 'MEDIUM': 1, 'HIGH': 2}
    return 2 if any(rank[f['severity']] >= rank[args.fail_on] for f in result['findings']) else 0
