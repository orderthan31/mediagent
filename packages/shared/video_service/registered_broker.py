"""Application-side registered-model queue, not a DB-free physical-agent wire.

Only exact attempt references cross MQ. The trusted standalone application worker
loads the committed request and transient keys from PG; it reuses the existing
intent/receipt/adoption fences, and ACKs after adoption and next-node dispatch.
"""
import json
import re

from .cpu_agents import canonical, digest
from .rabbitmq_transport import (
    BrokerConfig,
    BrokerError,
    Delivery,
    InvalidMessage,
    RabbitClient,
)

COMMAND = 'registered.command.v1'
ROLE = 'registered'


def decode_reference(delivery):
    try:
        if (delivery.message_type != COMMAND or delivery.content_type != 'application/json'
                or delivery.content_encoding not in (None, 'utf-8') or len(delivery.body) > 1024):
            raise ValueError()
        value = json.loads(delivery.body)
        if (not isinstance(value, dict)
                or set(value) != {'version', 'owner', 'job_id', 'attempt_id', 'request_sha256'}
                or type(value['version']) is not int or value['version'] != 1
                or any(not isinstance(value[k], str) or not re.fullmatch('[a-f0-9]{32}', value[k])
                       for k in ('owner', 'job_id', 'attempt_id'))
                or not isinstance(value['request_sha256'], str)
                or not re.fullmatch('[a-f0-9]{64}', value['request_sha256'])
                or value['attempt_id'] != delivery.message_id or value['job_id'] != delivery.correlation_id
                or canonical(value) != delivery.body):
            raise ValueError()
        return value
    except (ValueError, TypeError, KeyError, UnicodeError):
        raise InvalidMessage('invalid_registered_reference') from None


def reference(owner, command):
    kind = {'transcribe': 'transcription', 'translate': 'translation'}.get(command.get('agent', {}).get('id'))
    if (kind is None or type(command.get('protocol_version')) is not int or command['protocol_version'] != 1
            or not command.get(kind) or any(name in command for name in {'translation', 'transcription'} - {kind})):
        raise InvalidMessage('invalid_registered_request')
    value = {'version': 1, 'owner': owner, 'job_id': command['run_id'],
             'attempt_id': command['attempt_id'], 'request_sha256': digest(command)}
    delivery = Delivery(canonical(value), COMMAND, value['attempt_id'], value['job_id'])
    decode_reference(delivery)
    return delivery


class RegisteredBrokerConfig(BrokerConfig):
    @property
    def commands(self):
        return self.namespace + '.registered.commands.v1'

    @property
    def results(self):
        return self.namespace + '.registered.results.v1'

    @property
    def dead(self):
        return self.namespace + '.registered.dead.v1'

    def queue(self, role):
        if role not in {ROLE, 'result'}:
            raise ValueError('invalid_registered_role')
        return self.namespace + '.registered.' + role + '.v1'


class RegisteredRabbitClient(RabbitClient):
    roles = frozenset({ROLE})

    def publish(self, delivery):
        self._owner()
        decode_reference(delivery)
        try:
            self.channel.basic_publish(
                exchange=self.config.commands, routing_key=ROLE, body=delivery.body, mandatory=True,
                properties=self.sdk.BasicProperties(content_type='application/json', content_encoding='utf-8',
                    delivery_mode=2, type=COMMAND, message_id=delivery.message_id,
                    correlation_id=delivery.correlation_id, expiration='60000'),
            )
        except (OSError, self.sdk.exceptions.AMQPError):
            raise BrokerError('registered_publish_unconfirmed') from None
        return True


class RegisteredReceiver:
    def __init__(self, runtime, factory):
        from .rabbitmq_controller import BrokerController
        if (not getattr(factory, 'registered_policy_sha256', None)
                or runtime.translation_runtime is None or runtime.transcription_runtime is None):
            raise ValueError('registered_runtime_not_configured')
        self.controller = BrokerController(runtime, factory)
        self.runtime = runtime

    def receive(self, delivery):
        from .postgres import Conflict, Missing
        ref = decode_reference(delivery)
        try:
            with self.runtime.database.connection() as db:
                # Publisher holds this same lock until confirm AND published_at
                # commit. Never race that commit or run an uncommitted publication.
                self.runtime._job(db, ref['owner'], ref['job_id'], lock=True)
                row = db.execute('SELECT request,request_sha256 FROM node_runs WHERE owner_id=%s AND job_id=%s AND id=%s',
                    (ref['owner'], ref['job_id'], ref['attempt_id'])).fetchone()
                outbox = db.execute('SELECT payload,published_at,message_type FROM message_outbox WHERE owner_id=%s AND aggregate_id=%s AND id=%s',
                    (ref['owner'], ref['job_id'], ref['attempt_id'])).fetchone()
                if (not row or not outbox or not outbox['published_at'] or outbox['message_type'] != COMMAND
                        or row['request_sha256'] != ref['request_sha256']
                        or digest(row['request']) != ref['request_sha256']
                        or digest(outbox['payload']) != ref['request_sha256']):
                    raise InvalidMessage('registered_publication_not_committed')
                command = row['request']
                if reference(ref['owner'], command).body != delivery.body:
                    raise InvalidMessage('registered_request_mismatch')
            result = self.runtime.execute_command(ref['owner'], command)
            self.runtime.accept(ref['owner'], command, result)
            self.controller.dispatch(ref['owner'], ref['job_id'])
        except (Conflict, Missing):
            # Includes started/unknown receipts. Preserve them; never invoke again.
            raise InvalidMessage('registered_attempt_held') from None
