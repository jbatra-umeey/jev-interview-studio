import os
import tempfile
os.environ['DATABASE_PATH']=tempfile.mktemp(suffix='.db')
os.environ.pop('AI_API_KEY',None)
from fastapi.testclient import TestClient
from app.main import app

def auth(client,email):
    r=client.post('/api/auth/register',json={'email':email,'password':'very-secure-password-123'})
    assert r.status_code==201,r.text
    return {'Authorization':'Bearer '+r.json()['access_token']}

def test_end_to_end_and_isolation():
    with TestClient(app) as client:
        a=auth(client,'a@example.com')
        b=auth(client,'b@example.com')
        assert client.get('/api/stats').status_code==401
        qs=client.get('/api/questions?track=agentic-ai&difficulty=intermediate').json()
        session=client.post('/api/sessions',json={'track':'agentic-ai','difficulty':'intermediate'},headers=a)
        assert session.status_code==201
        sid=session.json()['id']
        assert client.get(f'/api/sessions/{sid}/history',headers=b).status_code==404
        assert client.post(f'/api/sessions/{sid}/answers',json={'question_idx':qs[0]['id'],'answer':'Detailed secure tool approval and audit strategy.'},headers=b).status_code==404
        answer=client.post(f'/api/sessions/{sid}/answers',json={'question_idx':qs[0]['id'],'answer':'Use strict tool scopes, approval, timeout, and audit logs to enforce security.'},headers=a)
        assert answer.status_code==200,answer.text
        assert answer.json()['mode']=='heuristic-demo'
        follow=client.post(f'/api/sessions/{sid}/followup',json={'question_idx':qs[0]['id'],'answer':'Use strict tool scopes, approval, timeout, and audit logs to enforce security.'},headers=a)
        assert follow.status_code==200,follow.text
        assert 'followup' in follow.json()
        assert client.get('/api/stats',headers=a).json()['total_attempts']==1
        assert client.get('/api/stats',headers=b).json()['total_attempts']==0
        assert client.get('/api/billing/status',headers=a).json()['tier']=='free'

def test_validation():
    with TestClient(app) as client:
        a=auth(client,'validation@example.com')
        assert client.post('/api/sessions',json={'track':'invalid'},headers=a).status_code==400
        session=client.post('/api/sessions',json={'track':'ios'},headers=a).json()
        assert client.post(f"/api/sessions/{session['id']}/answers",json={'question_idx':0,'answer':'This is a long enough response'},headers=a).status_code==400
        assert client.post('/api/auth/login',json={'email':'validation@example.com','password':'wrong-password!'}).status_code==401
