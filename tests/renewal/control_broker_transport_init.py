"""Explicit setup of NEW disposable TLS MQ and S3, no product/operating data."""
import json
import logging
import os
import time
from video_service.transport_files import broker_factory, object_store
logging.getLogger('pika').disabled=True
assert os.environ.get('MIDEAGENT_CONTROL_DISPOSABLE')=='1'
factory=broker_factory('/run/bootstrap/operator-broker.json');objects=object_store('/run/bootstrap/objects.json')
end=time.monotonic()+80
while True:
    try:
        with factory() as client:client.declare()
        break
    except Exception:
        if time.monotonic()>end:raise RuntimeError('isolated_mq_not_ready') from None
        time.sleep(.25)
while True:
    try:
        objects.client.create_bucket(Bucket=objects.bucket);objects.client.head_bucket(Bucket=objects.bucket);break
    except Exception:
        if time.monotonic()>end:raise RuntimeError('isolated_s3_not_ready') from None
        time.sleep(.25)
print(json.dumps({'new_mq_topology_ready':True,'new_s3_bucket_ready':True}))
