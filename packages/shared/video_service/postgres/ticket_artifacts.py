"""Immutable ticket storage bindings, anchored only by committed accepted runs.

The existing run receipt is the SQL authority: filesystem/object writes preceding
its transaction may leave unreferenced bytes, never an accepted artifact.
"""
from __future__ import annotations

import hashlib
import json

from ..cpu_agents import canonical
from . import Conflict, Missing


class TicketArtifacts:
    def __init__(self, store):
        self.store = store

    @staticmethod
    def enabled(job):
        return job['snapshot'].get('artifact_layout') == 1

    @staticmethod
    def key(job, run, port, reference, lane='outputs'):
        node = hashlib.sha256(run['node_id'].encode('utf-8')).hexdigest()
        return f'tickets/{job["id"]}/nodes/{node}/attempts/{run["id"]}/{lane}/{port}/{reference["sha256"]}'

    @staticmethod
    def entry(job, run, port, reference):
        used = any(edge['source'] == {'node': run['node_id'], 'port': port}
                   for edge in job['snapshot']['definition']['edges'])
        return {
            'ticket_id': job['id'], 'node_id': run['node_id'], 'node_run_id': run['id'],
            'attempt': run['attempt'], 'generation': run['generation'],
            'output_port': port, 'stage': 'intermediate' if used else 'final',
            'reference': reference,
        }

    def entries(self, job, runs):
        values = []
        for run in runs:
            if run['status'] != 'completed':
                continue
            receipt = run.get('result') or {}
            recorded = (receipt.get('ticket_artifacts') or {}).get('entries', [])
            outputs = receipt.get('outputs', {})
            if self.enabled(job) and len(recorded) != len(outputs):
                raise Conflict('티켓 산출물 기록이 완료 결과와 다릅니다.')
            for port, reference in outputs.items():
                expected = self.entry(job, run, port, reference)
                if not self.enabled(job):
                    values.append({**expected, 'storage': reference})
                    continue
                matches = [entry for entry in recorded if entry.get('output_port') == port]
                if len(matches) != 1:
                    raise Conflict('티켓 산출물 포트 기록 오류')
                entry = matches[0]
                storage = {**{k: reference[k] for k in ('sha256', 'bytes', 'type')},
                           'storage_key': self.key(job, run, port, reference)}
                if any(entry.get(k) != v for k, v in expected.items()) or entry.get('storage') != storage:
                    raise Conflict('티켓 산출물 저장 결속 오류')
                preview = receipt.get('previews', {}).get(port, {})
                if preview.get('status') == 'ready':
                    ref = preview['reference']
                    expected_preview = {**{k: ref[k] for k in ('sha256', 'bytes', 'type')},
                                        'storage_key': self.key(job, run, port, ref, 'previews')}
                    if entry.get('preview') != expected_preview:
                        raise Conflict('티켓 미리보기 저장 결속 오류')
                values.append(entry)
        return sorted(values, key=lambda entry: (entry['node_id'], entry['node_run_id'], entry['output_port']))

    def summary(self, job, runs):
        entries = self.entries(job, runs)
        manifests = [(run.get('result') or {}).get('ticket_artifacts', {}).get('manifest')
                     for run in runs if run['status'] == 'completed']
        manifests = [value for value in manifests if value]
        latest = max(manifests, key=lambda value: value['sequence']) if manifests else None
        if self.enabled(job) and entries and (not latest or latest['entry_count'] != len(entries)):
            raise Conflict('티켓 manifest가 완료 결과와 다릅니다.')
        return {
            'layout': 'ticket_v1' if self.enabled(job) else 'legacy_owner_cas',
            'reference': latest['reference'] if latest else None,
            'sequence': latest['sequence'] if latest else 0,
            'entry_count': len(entries),
        }

    @staticmethod
    def document(job, entries, sequence, layout):
        return {
            'version': 1, 'layout': layout, 'sequence': sequence,
            'ticket_id': job['id'], 'ticket_number': job['ticket_number'],
            'uploaded_by': job.get('asset_owner_id', job['owner_id']),
            'executed_by': job['owner_id'], 'entries': entries,
        }

    def capture(self, db, job, run, receipt):
        if not self.enabled(job):
            return receipt
        owner = job['owner_id']
        runs = db.execute('SELECT * FROM node_runs WHERE owner_id=%s AND job_id=%s ORDER BY id',
                          (owner, job['id'])).fetchall()
        entries = []
        for port, reference in receipt.get('outputs', {}).items():
            value = self.entry(job, run, port, reference)
            value['storage'] = self.store.bind_ticket(owner, self.key(job, run, port, reference), reference)
            preview = receipt.get('previews', {}).get(port, {})
            if preview.get('status') == 'ready':
                ref = preview['reference']
                value['preview'] = self.store.bind_ticket(owner, self.key(job, run, port, ref, 'previews'), ref)
            entries.append(value)
        other_runs = [item for item in runs if item['id'] != run['id']]
        summary = self.summary(job, other_runs)
        all_entries = sorted([*self.entries(job, other_runs), *entries],
                             key=lambda entry: (entry['node_id'], entry['node_run_id'], entry['output_port']))
        sequence = summary['sequence'] + 1
        document = self.document(job, all_entries, sequence, 'ticket_v1')
        reference = self.store.put(owner, [canonical(document)], 'ticket_manifest')
        reference = self.store.bind_ticket(owner, f'tickets/{job["id"]}/manifests/{reference["sha256"]}.json', reference)
        return {**receipt, 'ticket_artifacts': {'entries': entries, 'manifest': {
            'sequence': sequence, 'entry_count': len(all_entries), 'reference': reference,
        }}}

    def read(self, job, runs):
        summary = self.summary(job, runs)
        expected = self.document(job, self.entries(job, runs), summary['sequence'], summary['layout'])
        reference = summary['reference']
        if reference:
            if (reference['type'] != 'ticket_manifest' or
                    reference['storage_key'] != f'tickets/{job["id"]}/manifests/{reference["sha256"]}.json'):
                raise Conflict('티켓 manifest 저장 결속 오류')
            raw = self.store.read(job['owner_id'], reference)
            if json.loads(raw) != expected or raw != canonical(expected):
                raise Conflict('티켓 manifest 무결성 오류')
        else:
            # Compatibility projection only: no materialization or legacy writes.
            raw = canonical(expected)
        return raw

    def output(self, job, runs, run_id, port, *, preview=False):
        self.read(job, runs)
        entries = [entry for entry in self.entries(job, runs)
                   if entry['node_run_id'] == run_id and entry['output_port'] == port]
        if len(entries) != 1 or (preview and not entries[0].get('preview')):
            raise Missing('완료된 티켓 산출물을 찾을 수 없습니다.')
        entry = entries[0]
        reference = entry['preview'] if preview else entry['storage']
        return self.store.path(job['owner_id'], reference), reference['type']
