"""Shared media must not regress the accepted uncertainty projection. Disposable PG."""
from test_execution import db as db, admin as admin, movie as movie, runtime as runtime
from test_shared_library import clients
from test_job_processing_review import uncertain, original_rows

def test_shared_get_and_list_preserve_processing_projection(runtime,admin,db,movie):
    owner=admin[0]['id'];job,_,_=uncertain(runtime,owner,movie)
    app,a,b,other=clients(runtime,admin,db);before=original_rows(runtime,job['id'])
    for client in (a,b):
        detail=client.get('/api/renewal/jobs/'+job['id'])
        assert detail.status_code==200
        value=detail.json()
        assert value.get('processing_review',{}).get('state')=='needs_review'
        listing=client.get('/api/jobs').json()['jobs']
        row=next(v for v in listing if v['job_id']==job['id'])
        assert row['status']=='PROCESSING_REVIEW'
    assert original_rows(runtime,job['id'])==before
