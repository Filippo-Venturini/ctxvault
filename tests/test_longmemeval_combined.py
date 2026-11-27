"""Date-aware benchmark replay using real local stores and a deterministic model."""

import json
from pathlib import Path
import sys

import chromadb
import pytest

from ctxvault.storage import chroma_store

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmarks.longmemeval.data import parse_record
from benchmarks.longmemeval.replay import memory_for


@pytest.fixture
def native_chroma(tmp_path, monkeypatch):
    monkeypatch.setattr(chroma_store, 'PersistentClient', chromadb.PersistentClient)
    monkeypatch.setattr('ctxvault.utils.config.GLOBAL_DIR', tmp_path / 'global')
    yield
    for path in list(chroma_store._clients):
        chroma_store.close_client({'db_path': path})


def question(*, future=False):
    sessions = [[{'role': 'user', 'content': 'I live in Mestre. My door code is 814.'}]]
    dates = ['2026-01-10']
    if future:
        sessions.append([{'role': 'user', 'content': 'I moved to FutureCity, code 999.'}])
        dates.append('2026-03-10')
    return parse_record({
        'question_id': 'q_city', 'question_type': 'single-session-user',
        'question': 'Where do I live?', 'answer': 'Mestre',
        'question_date': '2026-02-10',
        'haystack_session_ids': [f's{i}' for i in range(len(sessions))],
        'haystack_dates': dates, 'haystack_sessions': sessions,
    })


class LinkedModel:
    name = 'local-deterministic'
    prompt_version = 'test'

    def extract(self, turns):
        city = 'FutureCity' if 'FutureCity' in turns[0].text else 'Mestre'
        return [{'subject': 'user', 'statement': f'The user lives in {city}',
                 'speaker': 'user', 'kind': 'first_party', 'turns': [0]}]

    def relate(self, claim, candidates):
        return {'relation': 'new'}


def test_semantic_replay_does_not_retrieve_future_sessions(tmp_path, native_chroma):
    memory = memory_for('semantic-only', question(future=True), workdir=tmp_path / 'work')
    assert 'Mestre' in memory
    assert '2026-01-10' in memory
    assert 'FutureCity' not in memory
    assert not chroma_store._clients


@pytest.mark.parametrize('config', ['episodic', 'episodic+semantic'])
@pytest.mark.parametrize('model_name', [None, 'test-custom-embedding'])
def test_episodic_replay_embeds_facts_and_candidates(tmp_path, native_chroma, config, model_name):
    from ctxvault import Client
    from ctxvault.core.embedding import DEFAULT_EMBEDDING_MODEL
    from ctxvault.storage import sqlite_store
    from benchmarks.longmemeval.replay import isolated_workdir

    record = parse_record({
        'question_id': 'q_vectors', 'question_type': 'single-session-user',
        'question': 'Where do I live?', 'answer': 'Mestre', 'question_date': '2026-02-10',
        'haystack_session_ids': ['city', 'garden'],
        'haystack_dates': ['2026-01-10', '2026-01-11'],
        'haystack_sessions': [
            [{'role': 'user', 'content': 'I live in Mestre.'}],
            [{'role': 'user', 'content': 'Winter vegetables taste delicious.'}],
        ],
    })

    class CandidateModel(LinkedModel):
        candidates = None

        def extract(self, turns):
            if 'Winter' in turns[0].text:
                return [{'subject': 'garden', 'statement': 'Winter vegetables taste delicious',
                         'kind': 'first_party', 'turns': [0]}]
            return super().extract(turns)

        def relate(self, claim, candidates):
            if claim.subject == 'garden':
                self.candidates = list(candidates)
            return {'relation': 'new'}

    model = CandidateModel()
    workdir = tmp_path / 'work'
    kwargs = {} if model_name is None else {'embedding_model': model_name}
    memory_for(config, record, workdir=workdir, extraction_model=model, **kwargs)
    with isolated_workdir(workdir):
        vault = Client().episodic('lme-facts' if config == 'episodic+semantic' else 'lme-episodic')
        assert vault.embedding_model == (model_name or DEFAULT_EMBEDDING_MODEL)
        rows = sqlite_store.select_episodes(vault.config)
        assert len(rows) == 2
        assert all(len(row['embedding']) == 384 for row in rows)
        # The fixture's identical vectors have cosine 1.0. These words have
        # no lexical overlap, so a keyword score cannot satisfy this check.
        matches = vault.query_episodes('Xylophone').results
        assert len(matches) == 2
        assert all(match.similarity == pytest.approx(1.0) for match in matches)
    # The garden claim has a different subject and disjoint wording. Only
    # vector similarity can bring the city fact into consolidation candidates.
    assert model.candidates
    assert model.candidates[0].content == 'The user lives in Mestre'
    assert model.candidates[0].similarity == pytest.approx(1.0)


def test_combined_replay_puts_facts_before_cited_text_and_excludes_future(tmp_path, native_chroma):
    diagnostics = dict(sessions_consolidated=0, sessions_with_unparseable_reply=0,
                       claims_written=0, claims_rejected=0)
    memory = memory_for('episodic+semantic', question(future=True), workdir=tmp_path / 'work',
                        extraction_model=LinkedModel(), diagnostics=diagnostics)
    assert memory.index('Episodic facts') < memory.index('Transcript fallback')
    assert 'The user lives in Mestre' in memory
    assert 'My door code is 814.' in memory
    assert 'FutureCity' not in memory
    assert '999' not in memory
    assert diagnostics['sessions_consolidated'] == 2
    assert diagnostics['claims_written'] == 2
    assert not chroma_store._clients


def test_combined_searches_transcripts_even_when_claims_are_uncited(tmp_path, native_chroma):
    class Uncited(LinkedModel):
        def extract(self, turns):
            claims = super().extract(turns)
            claims[0]['turns'] = []
            return claims

    memory = memory_for('episodic+semantic', question(), workdir=tmp_path / 'work',
                        extraction_model=Uncited())
    assert 'The user lives in Mestre' in memory
    assert 'My door code is 814.' in memory


@pytest.mark.parametrize('budget', [1, 2])
def test_combined_finds_a_detail_dropped_from_a_separate_session(tmp_path, native_chroma, budget):
    record = parse_record({
        'question_id': 'q_door', 'question_type': 'single-session-user',
        'question': 'What is the door code?', 'answer': '814',
        'question_date': '2026-02-10',
        'haystack_session_ids': ['city', 'door', 'future'],
        'haystack_dates': ['2026-01-10', '2026-01-11', '2026-03-10'],
        'haystack_sessions': [
            [{'role': 'user', 'content': 'I live in Mestre.'}],
            [{'role': 'user', 'content': 'My door code is 814.'}],
            [{'role': 'user', 'content': 'My new door code is 999.'}],
        ],
    })

    class CityOnly(LinkedModel):
        def extract(self, turns):
            return super().extract(turns) if 'Mestre' in turns[0].text else []

    memory = memory_for('episodic+semantic', record, workdir=tmp_path / 'work',
                        extraction_model=CityOnly(), n_results=budget)
    assert 'The user lives in Mestre' in memory
    assert ('My door code is 814.' in memory) == (budget == 2)
    if budget == 2:
        assert memory.index('I live in Mestre.') < memory.index('My door code is 814.')
    assert memory.count('I live in Mestre.') == 1
    assert '999' not in memory


def test_combined_deduplicates_a_chunk_shared_by_two_facts(tmp_path, native_chroma):
    class TwoClaims(LinkedModel):
        def extract(self, turns):
            first = super().extract(turns)[0]
            return [first, dict(first, subject='door', statement='The door has a code')]

    memory = memory_for('episodic+semantic', question(), workdir=tmp_path / 'work',
                        extraction_model=TwoClaims())
    assert 'The user lives in Mestre' in memory
    assert 'The door has a code' in memory
    assert memory.count('My door code is 814.') == 1


@pytest.mark.parametrize('change', ['changed', 'missing'])
def test_combined_refuses_unverifiable_transcript_text(tmp_path, native_chroma, monkeypatch, change):
    from benchmarks.longmemeval import replay
    from ctxvault import Client

    consolidate_session = replay.consolidate_session

    def consolidate_then_change(config, *args, **kwargs):
        result = consolidate_session(config, *args, **kwargs)
        vault = Client().semantic(config.transcripts_vault)
        if change == 'changed':
            vault.write_doc(result.transcript.path, 'Unverified replacement text', overwrite=True)
        else:
            vault.delete_file(vault.vault_path / result.transcript.path)
        return result

    monkeypatch.setattr(replay, 'consolidate_session', consolidate_then_change)
    memory = memory_for('episodic+semantic', question(), workdir=tmp_path / 'work',
                        extraction_model=LinkedModel())
    assert 'The user lives in Mestre' in memory
    assert 'door code' not in memory
    assert 'Unverified replacement' not in memory
    assert '(no retrieved transcript chunks)' in memory


def test_combined_releases_both_stores_when_extraction_fails(tmp_path, native_chroma):
    from ctxvault.storage import sqlite_store

    class Failing(LinkedModel):
        def extract(self, turns):
            raise RuntimeError('extraction stopped')

    with pytest.raises(RuntimeError, match='extraction stopped'):
        memory_for('episodic+semantic', question(), workdir=tmp_path / 'work', extraction_model=Failing())
    assert not chroma_store._clients
    assert not chroma_store._collections
    assert not sqlite_store._connections


def test_combined_run_writes_diagnostics_and_resumes_without_calls(tmp_path, native_chroma, monkeypatch):
    from benchmarks.longmemeval.run import parse_args, run

    data = tmp_path / 'mini.json'
    data.write_text(json.dumps([{
        'question_id': 'q_city', 'question_type': 'single-session-user',
        'question': 'Where do I live?', 'answer': 'Mestre', 'question_date': '2026-02-10',
        'haystack_session_ids': ['session'], 'haystack_dates': ['2026-01-10'],
        'haystack_sessions': [[{'role': 'user', 'content': 'I live in Mestre. My door code is 814.'}]],
    }]))
    calls = []

    class Reply:
        status_code = 200

        def __init__(self, text):
            self.text = text

        def json(self):
            return {'choices': [{'message': {'content': self.text}}],
                    'usage': {'prompt_tokens': 17, 'completion_tokens': 4}}

    def post(url, *, json: dict, **kwargs):
        calls.append(json)
        if json['model'] == 'extract':
            return Reply('{"claims":[{"subject":"user","statement":"The user lives in Mestre",'
                         '"kind":"first_party","turns":[0]}]}')
        return Reply('yes' if json['model'] == 'judge' else 'Mestre')

    monkeypatch.setattr('requests.post', post)
    base = ['--config', 'episodic+semantic', '--data', str(data), '--answer-model', 'answer',
            '--extract-model', 'extract', '--judge-model', 'judge',
            '--results-dir', str(tmp_path / 'results'), '--workdir', str(tmp_path / 'work')]
    out = run(parse_args(base))
    assert [body['model'] for body in calls] == ['extract', 'answer', 'judge']
    assert 'My door code is 814.' in calls[1]['messages'][-1]['content']
    manifest = json.loads((out / 'manifest.json').read_text())
    assert manifest['config'] == 'episodic+semantic'
    assert manifest['embedding_model'] == 'sentence-transformers/all-MiniLM-L6-v2'
    assert manifest['question_count'] == 1
    assert manifest['extraction_diagnostics']['sessions_consolidated'] == 1
    assert manifest['extraction_diagnostics']['claims_written'] == 1
    assert manifest['token_counts']['extract'] == {'in': 17, 'out': 4}
    assert json.loads((out / 'scores.json').read_text())['overall']['judge'] == 1
    assert not chroma_store._clients
    assert list((tmp_path / 'work').iterdir()) == []

    run(parse_args([*base, '--resume']))
    resumed = json.loads((out / 'manifest.json').read_text())
    assert len(calls) == 3
    assert resumed['token_counts'] == manifest['token_counts']
    assert resumed['extraction_diagnostics'] == manifest['extraction_diagnostics']


def test_combined_never_reuses_a_same_named_global_vault(tmp_path, native_chroma):
    from ctxvault import Client

    client = Client()
    for name, kind in [('lme-facts', 'episodic'), ('lme-transcripts', 'semantic'),
                       ('lme-episodic', 'episodic'), ('lme-semantic', 'semantic')]:
        client.init(name, kind, global_vault=True)
    for name in ('lme-facts', 'lme-episodic'):
        client.episodic(name).write_episode('Outside-benchmark sentinel', recorded_at='2001-01-01T00:00:00+00:00',
                                          valid_from='2001-01-01T00:00:00+00:00')

    memory = memory_for('episodic+semantic', question(), workdir=tmp_path / 'work',
                        extraction_model=LinkedModel())

    assert 'Outside-benchmark sentinel' not in memory
    for name in ('lme-facts', 'lme-episodic'):
        assert [episode.content for episode in client.episodic(name).all_episodes()] == ['Outside-benchmark sentinel']


def test_facts_have_their_own_budget(tmp_path, native_chroma):
    class ManyFacts(LinkedModel):
        def extract(self, turns):
            return [{'subject': 'user', 'statement': f'The user owns item number {i}',
                     'speaker': 'user', 'kind': 'first_party', 'durability': 'of_the_day'} for i in range(12)]

    def facts(**budget):
        # a folder name every platform accepts: Windows refuses quotes and colons
        name = '-'.join(f'{key}-{value}' for key, value in budget.items()) or 'default'
        memory = memory_for('episodic', question(), workdir=tmp_path / name,
                            extraction_model=ManyFacts(), **budget)
        return memory.count('The user owns item number')

    assert facts() == 12                       # the default leaves room for every fact here
    assert facts(n_results=3) == 12            # the chunk budget does not bound facts
    assert facts(n_facts=5) == 5


def test_the_manifest_records_the_fact_budget(tmp_path, native_chroma, monkeypatch):
    from benchmarks.longmemeval.run import parse_args, run

    data = tmp_path / 'mini.json'
    data.write_text(json.dumps([{
        'question_id': 'q_city', 'question_type': 'single-session-user',
        'question': 'Where do I live?', 'answer': 'Mestre', 'question_date': '2026-02-10',
        'haystack_session_ids': ['session'], 'haystack_dates': ['2026-01-10'],
        'haystack_sessions': [[{'role': 'user', 'content': 'I live in Mestre.'}]],
    }]))

    class Reply:
        status_code = 200
        def __init__(self, text): self.text = text
        def json(self):
            return {'choices': [{'message': {'content': self.text}}], 'usage': {'prompt_tokens': 1, 'completion_tokens': 1}}

    def post(url, *, json: dict, **kwargs):
        if json['model'] == 'extract':
            return Reply('{"claims":[{"subject":"user","statement":"The user lives in Mestre","kind":"first_party"}]}')
        return Reply('Answer: Mestre')

    monkeypatch.setattr('requests.post', post)
    base = ['--config', 'episodic', '--data', str(data), '--answer-model', 'answer', '--extract-model', 'extract',
            '--results-dir', str(tmp_path / 'results'), '--workdir', str(tmp_path / 'work')]
    out = run(parse_args([*base, '--n-facts', '12']))
    assert json.loads((out / 'manifest.json').read_text())['n_facts'] == 12
    with pytest.raises(SystemExit, match='n_facts differs'):
        run(parse_args([*base, '--n-facts', '20', '--resume']))
