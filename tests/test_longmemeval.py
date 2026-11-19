import hashlib
import io
import json
import sys
from pathlib import Path
from datetime import datetime, timezone

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmarks.longmemeval.chat import ChatClient, Completion, TokenMeter
from benchmarks.longmemeval.data import (
    SPLITS, download_split, load_from_path, parse_lme_datetime,
    parse_record, question_instant, sha256_file, to_iso,
)
from benchmarks.longmemeval.grade import content_words, grader_correct, parse_yes_no, judge_correct
from benchmarks.longmemeval.output import (
    build_scores, manifest_is_complete, read_hypotheses, append_hypothesis,
)
from benchmarks.longmemeval.prompts import answer_prompt, format_history, judge_prompt
from benchmarks.longmemeval.replay import ingest_episodic, isolated_workdir, memory_for
from benchmarks.longmemeval.report import collect, render
from benchmarks.longmemeval.run import parse_args, run
from ctxvault.consolidation import consolidate
from ctxvault.core import vault_router


def session(sid, date, user_text, assistant_text='Noted.'):
    return {
        'id': sid,
        'date': date,
        'turns': [
            {'role': 'user', 'content': user_text},
            {'role': 'assistant', 'content': assistant_text},
        ],
    }


def record(qid, qtype, question, answer, question_date, sessions):
    return {
        'question_id': qid,
        'question_type': qtype,
        'question': question,
        'answer': answer,
        'question_date': question_date,
        'haystack_session_ids': [s['id'] for s in sessions],
        'haystack_dates': [s['date'] for s in sessions],
        'haystack_sessions': [s['turns'] for s in sessions],
    }


MINI = [
    record(
        'q_city', 'single-session-user',
        'Where do I live?', 'Mestre',
        '2026/06/10 (Wed) 09:00',
        [
            session('s_later', '2026/03/10 (Tue) 11:00', 'I live in Mestre now.'),
            session('s_earlier', '2026/01/10 (Sat) 08:00', 'I used to live in Venezia.'),
        ],
    ),
    record(
        'q_job_abs', 'single-session-user',
        'What is my salary?', 'no information.',
        '2026/06/10 (Wed) 09:00',
        [session('s_job', '2026/04/01 (Wed) 10:00', 'I work as a baker.')],
    ),
]
MINI[1]['question_id'] = 'q_job_abs'


class ScriptedClient(ChatClient):
    '''A ChatClient that returns scripted replies and records prompts.'''

    def __init__(self, replies, meter=None):
        self.replies = list(replies)
        self.asked = []
        self.meter = meter or TokenMeter()
        self.base_url = 'http://127.0.0.1:9/v1'
        self.api_key = None
        self.timeout = 1

    def complete(self, model, *, stage, system=None, user, max_tokens=None, json_mode=False):
        self.asked.append({'model': model, 'stage': stage, 'system': system, 'user': user})
        text = self.replies.pop(0) if self.replies else 'yes'
        self.meter.stage(stage).add(10, 3)
        return Completion(text=text, prompt_tokens=10, completion_tokens=3)


class StubExtract:
    name = 'stub-extract'
    prompt_version = 'v0'

    def extract(self, turns):
        text = ' '.join(turn.text for turn in turns)
        if 'Mestre' in text:
            statement, subject = 'The user lives in Mestre', 'user'
        elif 'Venezia' in text:
            statement, subject = 'The user lived in Venezia', 'user'
        elif 'baker' in text:
            statement, subject = 'The user works as a baker', 'user'
        else:
            statement, subject = text, 'user'
        return [{'subject': subject, 'statement': statement, 'speaker': 'user', 'kind': 'first_party'}]

    def relate(self, claim, candidates):
        return {'relation': 'new'}


def write_mini(path: Path):
    path.write_text(json.dumps(MINI), encoding='utf-8')
    return path


class TestDates:
    def test_official_timestamp_is_utc(self):
        moment = parse_lme_datetime('2023/05/28 (Sun) 06:47')
        assert moment == datetime(2023, 5, 28, 6, 47, tzinfo=timezone.utc)
        assert to_iso('2023/05/28 (Sun) 06:47') == '2023-05-28T06:47:00+00:00'

    def test_iso_and_date_only_are_accepted(self):
        assert parse_lme_datetime('2026-03-10T09:00:00+00:00').hour == 9
        assert parse_lme_datetime('2026-03-10').day == 10

    def test_same_day_question_is_just_after_the_last_session(self):
        asked = question_instant('2023/05/20 (Sat) 02:21', '2023/05/20 (Sat) 14:30')
        last = parse_lme_datetime('2023/05/20 (Sat) 14:30')
        assert asked == last.replace(second=1) or asked.timestamp() == last.timestamp() + 1
        assert asked > last

    def test_a_later_day_is_left_alone(self):
        asked = question_instant('2023/05/21 (Sun) 02:21', '2023/05/20 (Sat) 14:30')
        assert asked == parse_lme_datetime('2023/05/21 (Sun) 02:21')


class TestLoader:
    def test_oracle_like_sessions_are_sorted_by_date(self):
        question = parse_record(MINI[0])
        assert [s.id for s in question.sessions] == ['s_earlier', 's_later']
        assert question.sessions[0].date.startswith('2026/01/10')

    def test_load_from_path_honours_limit(self, tmp_path):
        path = write_mini(tmp_path / 'mini.json')
        assert len(load_from_path(path)) == 2
        assert [q.question_id for q in load_from_path(path, limit=1)] == ['q_city']

    def test_abstention_is_the_id_suffix(self, tmp_path):
        question = load_from_path(write_mini(tmp_path / 'mini.json'))[1]
        assert question.abstention is True

    def test_download_reuses_a_file_with_the_right_checksum(self, tmp_path, monkeypatch):
        data = b'oracle-bytes'
        digest = hashlib.sha256(data).hexdigest()
        monkeypatch.setitem(SPLITS, 'oracle', {'filename': 'longmemeval_oracle.json', 'sha256': digest})
        dest = tmp_path / 'longmemeval_oracle.json'
        dest.write_bytes(data)
        calls = []

        def urlopen(request):
            calls.append(request)
            raise AssertionError('should not download')

        assert download_split('oracle', cache=tmp_path, urlopen=urlopen) == dest
        assert calls == []

    def test_download_rejects_a_checksum_mismatch(self, tmp_path, monkeypatch):
        monkeypatch.setitem(SPLITS, 'oracle', {
            'filename': 'longmemeval_oracle.json',
            'sha256': '0' * 64,
        })

        def urlopen(request):
            return io.BytesIO(b'not-the-dataset')

        with pytest.raises(ValueError, match='Checksum mismatch'):
            download_split('oracle', cache=tmp_path, urlopen=urlopen)
        assert not (tmp_path / 'longmemeval_oracle.json').exists()
        assert not list(tmp_path.glob('*.part'))


class TestGrader:
    def test_all_content_words_must_appear(self):
        assert grader_correct('The user lives in Mestre, Italy.', 'Mestre')
        assert not grader_correct('The user lives in Venezia.', 'Mestre')
        assert 'mestre' in content_words('I live in Mestre')

    def test_a_bare_number_is_matched_as_a_string(self):
        assert grader_correct('About 15 weeks passed.', '15')
        assert not grader_correct('About fourteen weeks passed.', '15')

    def test_yes_is_read_as_in_the_official_script(self):
        assert parse_yes_no('Yes') is True
        assert parse_yes_no('The answer is yes.') is True
        assert parse_yes_no('No') is False


class TestPrompts:
    def test_history_is_in_date_order_with_both_sessions(self, tmp_path):
        question = load_from_path(write_mini(tmp_path / 'mini.json'))[0]
        history = format_history(question.sessions)
        assert history.index('s_earlier') < history.index('s_later')
        assert 'I used to live in Venezia.' in history
        assert 'I live in Mestre now.' in history
        _, user = answer_prompt(question, history)
        assert 'Where do I live?' in user
        assert '2026-06-10T09:00:00+00:00' in user

    def test_judge_prompt_for_abstention_asks_unanswerable(self, tmp_path):
        question = load_from_path(write_mini(tmp_path / 'mini.json'))[1]
        prompt = judge_prompt(question, 'I do not have that information.')
        assert 'unanswerable' in prompt


class TestScoresAndReport:
    def test_scores_list_disagreements(self):
        rows = [
            {'question_id': 'a', 'question_type': 'multi-session', 'grader': True, 'judge': True},
            {'question_id': 'b', 'question_type': 'multi-session', 'grader': True, 'judge': False},
            {'question_id': 'c', 'question_type': 'knowledge-update', 'grader': False, 'judge': False},
        ]
        scores = build_scores(rows)
        assert scores['overall']['count'] == 3
        assert scores['overall']['grader'] == 0.6667
        assert scores['overall']['judge'] == 0.3333
        assert scores['per_question_type']['multi-session']['grader'] == 1.0
        assert [d['question_id'] for d in scores['disagreements']] == ['b']

    def test_report_merges_complete_folders_and_skips_incomplete_ones(self, tmp_path):
        good = tmp_path / 'full-context-oracle-stub'
        good.mkdir()
        (good / 'manifest.json').write_text(json.dumps({
            'ctxvault_commit': 'abc',
            'config': 'full-context',
            'split': 'oracle',
            'question_count': 2,
            'models': {'extraction': None, 'answer': 'stub', 'judge': 'stub'},
            'prompt_version': {'answer': 'lme-answer-1'},
            'token_counts': {'answer': {'in': 20, 'out': 6}, 'judge': {'in': 10, 'out': 2}, 'extract': {'in': 0, 'out': 0}, 'relate': {'in': 0, 'out': 0}},
            'wall_time_seconds': 1.5,
        }), encoding='utf-8')
        (good / 'scores.json').write_text(json.dumps({
            'overall': {'count': 2, 'grader': 0.5, 'judge': 1.0},
            'per_question_type': {},
            'disagreements': [],
        }), encoding='utf-8')
        bad = tmp_path / 'incomplete'
        bad.mkdir()
        (bad / 'manifest.json').write_text(json.dumps({'config': 'full-context'}), encoding='utf-8')
        (bad / 'scores.json').write_text('{}', encoding='utf-8')
        table = render(collect(tmp_path))
        assert 'full-context-oracle-stub' in table
        assert 'incomplete' not in table
        assert 'full-context' in table

    def test_an_empty_manifest_is_not_complete(self):
        assert manifest_is_complete({}) is False


class TestReplay(object):
    def test_episodic_plus_semantic_requires_an_extraction_model(self, tmp_path):
        question = parse_record(MINI[0])
        with pytest.raises(ValueError, match='extraction model'):
            memory_for('episodic+semantic', question, workdir=tmp_path / 'w')

    def test_full_context_does_not_open_a_vault(self, tmp_path):
        question = parse_record(MINI[0])
        memory = memory_for('full-context', question, workdir=tmp_path / 'w')
        assert 'I live in Mestre now.' in memory
        assert 'I used to live in Venezia.' in memory
        assert not (tmp_path / 'w' / '.ctxvault' / 'config.json').exists()

    def test_episodic_replay_uses_session_time_and_asks_as_of_the_question(self, tmp_path, monkeypatch):
        question = parse_record(MINI[0])
        model = StubExtract()
        monkeypatch.setattr('ctxvault.utils.config.GLOBAL_DIR', tmp_path / 'home-ctxvault')
        (tmp_path / 'home-ctxvault').mkdir()
        (tmp_path / 'home-ctxvault' / 'config.json').write_text('{"vaults": {}}')
        memory = memory_for(
            'episodic', question, workdir=tmp_path / 'q_city',
            extraction_model=model,
        )
        assert 'Mestre' in memory
        assert 'Venezia' in memory

    def test_consolidate_at_is_the_session_date(self, mock_episodic_vault_config):
        vault = vault_router.open_vault('test_episodic_vault')
        question = parse_record(MINI[0])
        ingest_episodic(vault, question.sessions, StubExtract())
        episodes = vault.all_episodes()
        recorded = sorted(ep.recorded_at for ep in episodes)
        assert recorded[0].startswith('2026-01-10T08:00:00')
        assert recorded[1].startswith('2026-03-10T11:00:00')


class TestRun:
    def test_full_context_run_writes_the_contract_and_can_resume(self, tmp_path, monkeypatch):
        data = write_mini(tmp_path / 'mini.json')
        results = tmp_path / 'results'
        replies = ['Mestre, in Italy.', 'yes', 'I do not have that information.', 'yes']
        scripted = ScriptedClient(replies)

        def fake_client(**kwargs):
            scripted.meter = kwargs.get('meter') or scripted.meter
            return scripted

        monkeypatch.setattr('benchmarks.longmemeval.run.ChatClient', fake_client)
        args = parse_args([
            '--config', 'full-context',
            '--data', str(data),
            '--answer-model', 'stub-answer',
            '--judge-model', 'stub-judge',
            '--results-dir', str(results),
            '--run-name', 'test-run',
            '--workdir', str(tmp_path / 'work'),
        ])
        out = run(args)
        lines = read_hypotheses(out / 'hypotheses.jsonl')
        assert [row['question_id'] for row in lines] == ['q_city', 'q_job_abs']
        assert lines[0]['hypothesis'] == 'Mestre, in Italy.'
        manifest = json.loads((out / 'manifest.json').read_text())
        assert manifest_is_complete(manifest)
        assert manifest['config'] == 'full-context'
        assert manifest['question_count'] == 2
        assert manifest['models']['answer'] == 'stub-answer'
        assert manifest['models']['judge'] == 'stub-judge'
        assert manifest['token_counts']['answer']['in'] == 20
        scores = json.loads((out / 'scores.json').read_text())
        assert scores['overall']['count'] == 2
        assert scores['overall']['grader'] == 1.0
        assert scores['overall']['judge'] == 1.0

        # Resume must not call the answer model again for questions already written.
        scripted.replies = ['should-not-be-used']
        scripted.asked.clear()
        args = parse_args([
            '--config', 'full-context',
            '--data', str(data),
            '--answer-model', 'stub-answer',
            '--judge-model', 'stub-judge',
            '--results-dir', str(results),
            '--run-name', 'test-run',
            '--resume',
            '--workdir', str(tmp_path / 'work'),
        ])
        run(args)
        assert scripted.asked == []
        assert len(read_hypotheses(out / 'hypotheses.jsonl')) == 2


class TestReviewRegressions:
    def test_resume_carries_all_stages_and_wall_time_through_a_noop(self, tmp_path, monkeypatch):
        data = tmp_path / 'three.json'
        preference = dict(MINI[0], question_id='q_preference', question_type='single-session-preference')
        data.write_text(json.dumps([*MINI, preference]))
        scripted = ScriptedClient(['Mestre', 'yes', 'unknown', 'yes', 'Mestre', 'yes'])
        clock = [0.0]
        complete = scripted.complete

        def timed_complete(*args, **kwargs):
            clock[0] += 2
            return complete(*args, **kwargs)

        scripted.complete = timed_complete

        def client(**kwargs):
            scripted.meter = kwargs['meter']
            return scripted

        monkeypatch.setattr('benchmarks.longmemeval.run.ChatClient', client)
        monkeypatch.setattr('benchmarks.longmemeval.run.time.monotonic', lambda: clock[0])
        base = ['--config', 'full-context', '--data', str(data), '--answer-model', 'stub',
                '--judge-model', 'judge', '--results-dir', str(tmp_path / 'results')]
        out = run(parse_args([*base, '--limit', '1']))
        assert out.name == 'full-context-custom-stub'
        first = json.loads((out / 'manifest.json').read_text())
        assert first['wall_time_seconds'] == 4
        assert first['token_counts']['answer'] == {'in': 10, 'out': 3}
        run(parse_args([*base, '--limit', '3', '--resume']))
        manifest = json.loads((out / 'manifest.json').read_text())
        assert manifest['question_count'] == 3
        assert manifest['token_counts']['answer'] == {'in': 30, 'out': 9}
        assert manifest['token_counts']['judge'] == {'in': 30, 'out': 9}
        assert manifest['wall_time_seconds'] == 12
        assert manifest['n_results'] == 8
        assert manifest['embedding_model'] is None
        assert manifest['dataset_sha256'] == sha256_file(data)
        calls = len(scripted.asked)
        run(parse_args([*base, '--limit', '3', '--resume']))
        assert len(scripted.asked) == calls
        assert json.loads((out / 'manifest.json').read_text()) == manifest
        scores = json.loads((out / 'scores.json').read_text())
        assert scores['overall']['grader'] == 1.0
        assert scores['disagreements'] == []
        labels = json.loads((out / '_labels.json').read_text())
        assert labels['q_job_abs']['grader'] is None
        assert labels['q_preference']['grader'] is None

    def test_each_vault_is_removed_before_the_next_question_and_workdir_is_preserved(self, tmp_path, monkeypatch):
        data = write_mini(tmp_path / 'mini.json')
        root = tmp_path / 'work'
        root.mkdir()
        sentinel = root / 'caller-owned.txt'
        sentinel.write_text('keep')
        vaults = []

        def memory(config, question, *, workdir, **kwargs):
            assert all(not path.exists() for path in vaults)
            vaults.append(workdir)
            (workdir / 'vault.sqlite').write_text('temporary')
            return 'memory'

        monkeypatch.setattr('benchmarks.longmemeval.run.memory_for', memory)
        monkeypatch.setattr('benchmarks.longmemeval.run.ChatClient',
                            lambda **kw: ScriptedClient(['Mestre', 'unknown'], meter=kw['meter']))
        run(parse_args(['--config', 'full-context', '--data', str(data), '--answer-model', 'stub',
                        '--results-dir', str(tmp_path / 'results'), '--workdir', str(root)]))
        assert all(not path.exists() for path in vaults)
        assert list(root.iterdir()) == [sentinel]

    def test_null_grader_overrides_legacy_cached_labels(self, tmp_path):
        from benchmarks.longmemeval.run import grade_rows
        questions = load_from_path(write_mini(tmp_path / 'mini.json'))
        preference = parse_record(dict(MINI[0], question_id='preference', question_type='single-session-preference'))
        questions.append(preference)
        labels = {q.question_id: {'grader': False, 'judge': True} for q in questions}
        labels['q_city']['grader'] = True
        rows = grade_rows(questions, {q.question_id: 'Mestre' for q in questions}, labels,
                          ScriptedClient([]), 'judge')
        assert [row['grader'] for row in rows] == [True, None, None]
        assert build_scores(rows)['overall']['grader'] == 1.0
        assert build_scores(rows)['disagreements'] == []

    def test_prompt_now_matches_the_retrieval_instant(self):
        question = parse_record(dict(MINI[0], question_date='2026/03/10 (Tue) 00:00'))
        _, prompt = answer_prompt(question, 'memory')
        expected = to_iso(question_instant(question.question_date, question.last_session_date))
        assert f'Today is {expected}.' in prompt
        assert expected == '2026-03-10T11:00:01+00:00'

    def test_judge_can_use_an_independent_endpoint_and_key_with_shared_accounting(self, tmp_path, monkeypatch):
        seen = []

        def client(**kwargs):
            seen.append(kwargs)
            replies = ['yes', 'yes'] if ':19002/' in kwargs['base_url'] else ['Mestre', 'unknown']
            return ScriptedClient(replies, meter=kwargs['meter'])

        monkeypatch.setattr('benchmarks.longmemeval.run.ChatClient', client)
        out = run(parse_args([
            '--config', 'full-context', '--data', str(write_mini(tmp_path / 'mini.json')),
            '--answer-model', 'answer', '--judge-model', 'judge',
            '--base-url', 'http://127.0.0.1:19001/v1', '--api-key', 'synthetic-answer-key',
            '--judge-base-url', 'http://127.0.0.1:19002/v1', '--judge-api-key', 'synthetic-judge-key',
            '--results-dir', str(tmp_path / 'results'),
        ]))
        assert len(seen) == 2
        assert seen[0]['api_key'] == 'synthetic-answer-key'
        assert seen[1]['api_key'] == 'synthetic-judge-key'
        assert seen[0]['meter'] is seen[1]['meter']
        manifest = json.loads((out / 'manifest.json').read_text())
        assert manifest['token_counts']['answer']['in'] == 20
        assert manifest['token_counts']['judge']['in'] == 20
        assert 'synthetic-' not in (out / 'manifest.json').read_text()

    def test_episodic_uses_public_endpoint_and_records_real_pipeline_results(self, tmp_path, monkeypatch):
        replies = iter([
            json.dumps({'claims': [
                {'subject': 'user', 'statement': 'The user lived in Venezia',
                 'speaker': 'user', 'kind': 'first_party'},
                {'not_a_claim': True},
            ]}),
            'not JSON', 'Mestre', '{"claims": []}', 'unknown',
        ])

        class Reply:
            status_code = 200

            def json(self):
                return {'choices': [{'message': {'content': next(replies)}}],
                        'usage': {'prompt_tokens': 10, 'completion_tokens': 3}}

        monkeypatch.setattr('requests.post', lambda *args, **kw: Reply())
        home = tmp_path / 'global'
        home.mkdir()
        (home / 'config.json').write_text('{"vaults": {}}')
        monkeypatch.setattr('ctxvault.utils.config.GLOBAL_DIR', home)
        base = ['--config', 'episodic', '--data', str(write_mini(tmp_path / 'mini.json')),
                '--answer-model', 'answer', '--extract-model', 'extract',
                '--results-dir', str(tmp_path / 'results')]
        out = run(parse_args([*base, '--limit', '1']))
        partial = json.loads((out / 'manifest.json').read_text())
        assert partial['extraction_diagnostics']['sessions_consolidated'] == 2
        run(parse_args([*base, '--resume']))
        manifest = json.loads((out / 'manifest.json').read_text())
        assert manifest['extraction_diagnostics'] == {
            'sessions_consolidated': 3, 'sessions_with_unparseable_reply': 1,
            'claims_written': 1, 'claims_rejected': 1,
        }
        assert manifest['embedding_model'] == 'sentence-transformers/all-MiniLM-L6-v2'
        assert manifest['token_counts']['extract'] == {'in': 30, 'out': 9}
        assert manifest['token_counts']['answer'] == {'in': 20, 'out': 6}
        run(parse_args([*base, '--resume']))
        resumed = json.loads((out / 'manifest.json').read_text())
        assert resumed['extraction_diagnostics'] == manifest['extraction_diagnostics']
        assert resumed['token_counts'] == manifest['token_counts']

    def test_resume_refuses_a_different_dataset_instead_of_mixing_results(self, tmp_path, monkeypatch):
        data = write_mini(tmp_path / 'mini.json')
        monkeypatch.setattr('benchmarks.longmemeval.run.ChatClient',
                            lambda **kw: ScriptedClient(['Mestre'], meter=kw['meter']))
        base = ['--config', 'full-context', '--data', str(data), '--answer-model', 'stub',
                '--results-dir', str(tmp_path / 'results'), '--limit', '1']
        run(parse_args(base))
        data.write_text(json.dumps(MINI) + ' ')
        with pytest.raises(SystemExit, match='dataset_sha256 differs'):
            run(parse_args([*base, '--resume']))

    def test_interrupted_answer_is_accounted_only_when_saved_on_resume(self, tmp_path, monkeypatch):
        scripted = ScriptedClient(['Mestre', 'unknown'])
        complete = scripted.complete

        def fail_after_usage(*args, **kwargs):
            result = complete(*args, **kwargs)
            if len(scripted.asked) == 2:
                raise RuntimeError('interrupted after response')
            return result

        scripted.complete = fail_after_usage

        def client(**kwargs):
            scripted.meter = kwargs['meter']
            return scripted

        monkeypatch.setattr('benchmarks.longmemeval.run.ChatClient', client)
        base = ['--config', 'full-context', '--data', str(write_mini(tmp_path / 'mini.json')),
                '--answer-model', 'stub', '--results-dir', str(tmp_path / 'results')]
        with pytest.raises(RuntimeError, match='interrupted'):
            run(parse_args(base))
        manifest = json.loads((tmp_path / 'results' / 'full-context-custom-stub' / 'manifest.json').read_text())
        assert manifest['question_count'] == 1
        assert manifest['token_counts']['answer'] == {'in': 10, 'out': 3}
        run(parse_args([*base, '--resume']))
        manifest = json.loads((tmp_path / 'results' / 'full-context-custom-stub' / 'manifest.json').read_text())
        assert manifest['question_count'] == 2
        assert manifest['token_counts']['answer'] == {'in': 20, 'out': 6}


    @pytest.mark.parametrize('failure', ['memory', 'hypothesis'])
    def test_failed_question_does_not_duplicate_extraction_totals_on_resume(self, tmp_path, monkeypatch, failure):
        from benchmarks.longmemeval import run as runner

        fail = [True]
        append = runner.append_hypothesis

        def memory(config, question, *, extraction_model, diagnostics, **kwargs):
            extraction_model.usage_callback('extract', 10, 3)
            extraction_model.usage_callback('relate', 5, 2)
            diagnostics['sessions_consolidated'] += len(question.sessions)
            diagnostics['claims_written'] += 1
            if fail[0] and question.question_id == 'q_job_abs' and failure == 'memory':
                raise RuntimeError('interrupted memory')
            return 'memory'

        def append_or_fail(path, question_id, hypothesis):
            if fail[0] and question_id == 'q_job_abs' and failure == 'hypothesis':
                raise RuntimeError('interrupted hypothesis')
            append(path, question_id, hypothesis)

        monkeypatch.setattr(runner, 'memory_for', memory)
        monkeypatch.setattr(runner, 'append_hypothesis', append_or_fail)
        monkeypatch.setattr(runner, 'ChatClient', lambda **kw: ScriptedClient(['Mestre', 'unknown'], meter=kw['meter']))
        base = ['--config', 'episodic', '--data', str(write_mini(tmp_path / 'mini.json')),
                '--answer-model', 'stub', '--results-dir', str(tmp_path / 'results')]
        with pytest.raises(RuntimeError, match='interrupted'):
            run(parse_args(base))
        path = tmp_path / 'results' / 'episodic-custom-stub' / 'manifest.json'
        partial = json.loads(path.read_text())
        assert partial['question_count'] == 1
        assert partial['extraction_diagnostics']['sessions_consolidated'] == 2
        assert partial['token_counts']['extract'] == {'in': 10, 'out': 3}
        assert partial['token_counts']['relate'] == {'in': 5, 'out': 2}
        assert partial['token_counts']['answer'] == {'in': 10, 'out': 3}

        fail[0] = False
        run(parse_args([*base, '--resume']))
        complete = json.loads(path.read_text())
        assert complete['question_count'] == 2
        assert complete['extraction_diagnostics']['sessions_consolidated'] == 3
        assert complete['extraction_diagnostics']['claims_written'] == 2
        assert complete['token_counts']['extract'] == {'in': 20, 'out': 6}
        assert complete['token_counts']['relate'] == {'in': 10, 'out': 4}
        assert complete['token_counts']['answer'] == {'in': 20, 'out': 6}

    def test_remote_judge_requires_explicit_remote_permission(self, tmp_path, monkeypatch):
        def unexpected_request(*args, **kwargs):
            raise AssertionError('No model call is allowed before endpoint validation')

        monkeypatch.setattr('requests.post', unexpected_request)
        with pytest.raises(ValueError, match='allow-remote'):
            run(parse_args([
                '--config', 'full-context', '--data', str(write_mini(tmp_path / 'mini.json')),
                '--answer-model', 'local', '--judge-model', 'hosted',
                '--judge-base-url', 'https://example.com/v1',
                '--results-dir', str(tmp_path / 'results'),
            ]))

    def test_diagnostics_count_a_contradiction_once_per_claim(self, mock_episodic_vault_config):
        class Contradiction(StubExtract):
            def relate(self, claim, candidates):
                return {'relation': 'contradicts', 'episode_id': candidates[0].id}

        vault = vault_router.open_vault('test_episodic_vault')
        stats = {'sessions_consolidated': 0, 'sessions_with_unparseable_reply': 0,
                 'claims_written': 0, 'claims_rejected': 0}
        ingest_episodic(vault, parse_record(MINI[0]).sessions, Contradiction(), diagnostics=stats)
        assert stats == {'sessions_consolidated': 2, 'sessions_with_unparseable_reply': 0,
                         'claims_written': 2, 'claims_rejected': 0}
        assert len(vault.all_episodes()) == 2

    def test_diagnostics_count_a_refused_write(self, mock_episodic_vault_config, monkeypatch):
        vault = vault_router.open_vault('test_episodic_vault')

        def refused(*args, **kwargs):
            raise ValueError('refused by vault')

        monkeypatch.setattr(vault, 'write_episode', refused)
        stats = {'sessions_consolidated': 0, 'sessions_with_unparseable_reply': 0,
                 'claims_written': 0, 'claims_rejected': 0}
        ingest_episodic(vault, parse_record(MINI[1]).sessions, StubExtract(), diagnostics=stats)
        assert stats['sessions_consolidated'] == 1
        assert stats['claims_written'] == 0
        assert stats['claims_rejected'] == 1
