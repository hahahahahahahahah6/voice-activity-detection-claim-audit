import ast
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from voice_activity_detection_claim_audit.audit import audit, claims, evidence, main, normalize
from voice_activity_detection_claim_audit import phrases

class AuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1])
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
    def put(self, name, text):
        path = self.root/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    def run_cli(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main([str(self.root), '--json', *args])
        return code, json.loads(out.getvalue())
    def test_phrase_oracle(self):
        tree = ast.parse(Path(phrases.__file__).read_text())
        lists = {node.targets[0].id: ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)}
        expected_vad = ('voice activity detection', 'voice activity detector', 'supports voice activity detection', 'support voice activity detection', 'voice activity detection support', 'voice activity detection capabilities', 'detects voice activity', 'detect voice activity', 'detects speech activity', 'speech activity detection', 'supports speech activity detection', 'detects speech', 'detect speech', 'speech detection', 'voice detection', 'detects voice', 'detect voice', 'detects when someone is speaking', 'detects when speech starts', 'detects speech segments', 'detect speech segments', 'identifies speech segments', 'identify speech segments', 'speech segments', 'segments speech', 'segment speech', 'speech segmentation', 'voice segmentation', 'segments voice activity', 'speech endpointing', 'endpoint detection', 'detects speech endpoints', 'detects speech boundaries', 'speech boundaries', 'identifies when speech occurs', 'finds speech segments', 'vad support', 'supports vad', 'support vad', 'vad capabilities', 'vad enabled', 'detects talking', 'spoken segment detection', 'detects spoken segments')
        expected_novad = ('no voice activity detection', 'does not detect voice activity', 'without voice activity detection', 'no vad', 'without vad', 'no vad support', 'does not support vad', 'vad not supported', 'does not support voice activity detection', 'voice activity detection not supported', 'does not detect speech', 'without speech detection', 'no speech detection', 'cannot detect voice activity', 'never detects voice activity', 'no speech activity detection', 'without speech activity detection', 'does not detect speech segments', 'without speech segments', 'no speech segmentation', 'does not segment speech', 'without voice detection', 'no voice detection', 'does not detect when someone is speaking', 'cannot detect speech', 'does not detect speech activity', 'no voice segmentation', 'does not detect spoken segments', 'without speech segmentation', 'cannot detect speech segments')
        self.assertEqual(lists['VAD'], expected_vad)
        self.assertEqual(lists['NOVAD'], expected_novad)
        self.assertEqual(len(expected_vad), 44)
        self.assertEqual(len(expected_novad), 30)
    def test_good(self):
        self.put('README.md', 'detects voice activity')
        self.put('app.py', 'import webrtcvad\nx.is_speech(b"", 16000)')
        self.assertEqual(self.run_cli()[0], 0)
        self.assertEqual(audit(self.root)['verdict'], 'PASS')
    def test_bad(self):
        self.put('README.md', 'detects voice activity')
        code, result = self.run_cli()
        self.assertEqual(code, 2)
        self.assertEqual(result['findings'], [dict(rule_id='documented-voice-activity-detection-claim-false', severity='HIGH', message='Documented claim lacks production source evidence.')])
    def test_test_only(self):
        self.put('README.md', 'detects voice activity')
        self.put('tests/a.py', 'x.get_speech_segments()')
        code, result = self.run_cli()
        self.assertEqual(code, 0)
        self.assertEqual(result['findings'][0]['severity'], 'MEDIUM')
        self.assertEqual(self.run_cli('--fail-on', 'MEDIUM')[0], 2)
    def test_denial(self):
        self.put('README.md', 'does not detect voice activity')
        self.assertEqual(self.run_cli()[1]['verdict'], 'PASS')
        self.put('app.py', 'x.get_speech_segments()')
        code, result = self.run_cli()
        self.assertEqual(code, 2)
        self.assertEqual(result['findings'][0]['rule_id'], 'documented-no-voice-activity-detection-claim-false')
        self.assertEqual(result['findings'][0]['severity'], 'HIGH')
    def test_no_claim(self):
        self.put('README.md', 'An audio utility.')
        self.assertEqual(audit(self.root)['verdict'], 'PASS')
    def test_single_module(self):
        self.put('README.md', 'detects speech')
        self.put('a.py', 'import webrtcvad')
        self.put('b.py', 'v.is_speech()')
        self.assertEqual(self.run_cli()[0], 2)
    def test_document_selection(self):
        self.put('other.md', 'detects speech')
        self.assertEqual(audit(self.root)['verdict'], 'PASS')
        self.put('nested/docs/a.md', 'detects speech')
        self.assertEqual(self.run_cli()[0], 2)
        self.assertEqual(self.run_cli('--ignore', 'nested')[0], 0)
    def test_symlinks(self):
        self.put('real.py', 'x.get_speech_segments()')
        (self.root/'linked.py').symlink_to(self.root/'real.py')
        (self.root/'linked').symlink_to(self.root, target_is_directory=True)
        self.assertEqual(audit(self.root)['production_evidence'], ['real.py'])
    def test_entry_points(self):
        result = subprocess.run([sys.executable, '-m', 'voice_activity_detection_claim_audit', '--version'], capture_output=True, text=True)
        self.assertEqual((result.returncode, result.stdout.strip()), (0, '0.1.0'))
        from importlib.metadata import entry_points
        # Source checkout need not be installed; installed dists exercise the console script separately.
    def test_usage(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as cm:
                main(['--unknown'])
            self.assertEqual(cm.exception.code, 1)
            self.assertEqual(main([str(self.root/'missing')]), 1)

def add_case(name, source, expected):
    def test(self):
        self.assertEqual(evidence(source), expected)
    setattr(AuditTests, 'test_evidence_' + name, test)

add_case('webrtc', 'import webrtcvad\nv.is_speech()', True)
add_case('web_alias', 'import webrtcvad as w\nw.Vad().is_speech()', True)
add_case('web_from', 'from webrtcvad import Vad as V\nV().is_speech()', True)
add_case('silero', 'm.get_speech_timestamps()', True)
add_case('silero_bare', 'get_speech_timestamps()', True)
add_case('pyannote', 'import pyannote.audio\npyannote.audio.Pipeline.from_pretrained("pyannote/segmentation")', True)
add_case('pyannote_alias', 'from pyannote.audio import Pipeline as P\nP.from_pretrained(model="SEGMENTATION")', True)
add_case('pyannote_module_alias', 'import pyannote.audio as pa\npa.Pipeline.from_pretrained("segmentation")', True)
add_case('ina', 'import inaSpeechSegmenter\ninaSpeechSegmenter.Segmenter()', True)
add_case('ina_alias', 'from inaSpeechSegmenter import Segmenter as S\nS()', True)
add_case('generic', 'm.get_speech_segments()', True)
add_case('import', 'import webrtcvad\nimport silero_vad', False)
add_case('load', 'load_silero_vad()', False)
add_case('no_segmentation', 'from pyannote.audio import Pipeline\nPipeline.from_pretrained("speaker-diarization")', False)
add_case('wrong_segmenter', 'from other import Segmenter\nSegmenter()', False)
add_case('shadow_pipeline', 'from pyannote.audio import Pipeline\nclass Pipeline: pass\nPipeline.from_pretrained("segmentation")', False)
add_case('shadow_ina', 'from inaSpeechSegmenter import Segmenter\ndef Segmenter(): pass\nSegmenter()', False)
add_case('shadow_assign_is_speech', 'import webrtcvad\nis_speech = 5\nvad.is_speech(b"", 16000)', True)
add_case('shadow_param_is_speech', 'import webrtcvad\ndef f(is_speech):\n    return vad.is_speech(b"", 16000)', True)
add_case('shadow_param_segments', 'def f(get_speech_segments):\n    return x.get_speech_segments()', True)
add_case('shadow_web', 'import webrtcvad\ndef is_speech(): pass\nv.is_speech()', False)
add_case('shadow_silero', 'def get_speech_timestamps(): pass\nx.get_speech_timestamps()', False)
add_case('shadow_segments', 'class A:\n def get_speech_segments(self): pass\nx.get_speech_segments()', False)
add_case('shadow_alias', 'import inaSpeechSegmenter as s\ns = other\ns.Segmenter()', False)
add_case('invalid', 'import webrtcvad\nv.is_speech((', False)
add_case('bare_reference', 'import webrtcvad\nv.is_speech', False)
add_case('transcription', 'whisper.transcribe(audio)', False)
add_case('recognition', 'r.recognize_google(audio)', False)
add_case('transformers', 'pipeline("automatic-speech-recognition")', False)
add_case('verification', 'speaker.verify(a,b)', False)
add_case('diarization', 'model.diarize(audio)', False)
add_case('capture', 'microphone.record()', False)
add_case('playback', 'audio.play()', False)
add_case('pydub', 'silence.detect_nonsilent(audio)', False)
add_case('librosa', 'librosa.effects.trim(audio)', False)
add_case('language', 'model.detect_language(audio)', False)
add_case('tts', 'engine.say("hi")', False)
add_case('string', 's="webrtcvad is_speech"', False)
add_case('subprocess', 'subprocess.run(["vad", "audio.wav"])', False)

def add_exclusion(name):
    def test(self):
        self.put('README.md', 'detects speech')
        self.put(name, 'x.get_speech_segments()')
        result = audit(self.root)
        self.assertFalse(result['production_evidence'])
        self.assertEqual(result['findings'][0]['severity'], 'MEDIUM' if name.startswith('tests/') or Path(name).name.startswith('test_') or name.endswith('_test.py') else 'HIGH')
    setattr(AuditTests, 'test_exclusion_' + name.replace('/', '_').replace('.', '_'), test)
for name in ['fixtures/a.py', 'docs/a.py', 'examples/a.py', 'tests/a.py', 'test_app.py', 'app_test.py']:
    add_exclusion(name)

def add_claim(name, text, expected):
    def test(self):
        pos, neg = claims(text)
        self.assertEqual((bool(pos), bool(neg)), expected)
    setattr(AuditTests, 'test_claim_' + name, test)
add_claim('fenced', '```\ndetects speech\n```', (False, False))
add_claim('tilde', '   ~~~~\ndetects speech\n   ~~~~', (False, False))
add_claim('inline', '`detects speech`', (True, False))
add_claim('negative', "doesn't detect voice-activity", (False, True))
add_claim('boundary', 'undetect speechy', (False, False))
add_claim('paragraph', 'detects\n\nspeech', (False, False))
add_claim('both', 'no vad. detects speech', (True, True))
