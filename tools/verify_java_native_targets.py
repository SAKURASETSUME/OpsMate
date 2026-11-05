"""Final authorized native-process/task tests against an isolated candidate server."""
from __future__ import annotations
import argparse
import json
import sys
import threading
import time
from pathlib import Path
from http.server import ThreadingHTTPServer
import httpx
from verify_java_assistant import Model,alive
from verify_java_generation import events


def main() -> None:
    parser=argparse.ArgumentParser()
    parser.add_argument('--url',required=True)
    parser.add_argument('--trial',required=True,type=Path)
    args=parser.parse_args()
    trial=args.trial.resolve(strict=True)
    assert (trial/'OpsMate/OpsMate.exe').is_file()
    marker=trial/'dedicated-process.pid'
    model=ThreadingHTTPServer(('127.0.0.1',0),Model)
    threading.Thread(target=model.serve_forever,daemon=True).start()
    task='acceptance_'+str(int(time.time()))
    result={'dedicated_process_terminated':False,'task_create_list_delete':False,'task_cleanup':False}
    created=False
    mcp_id=None
    try:
        with httpx.Client(base_url=args.url,trust_env=False,timeout=40) as client:
            assert client.get('/api/health').json()['ok']
            client.put('/api/settings',json={'provider':'custom','base_url':f'http://127.0.0.1:{model.server_port}','model':'normal','api_key':'desktop-synthetic-key'}).raise_for_status()
            marker.unlink(missing_ok=True)
            # Start the dedicated process from the candidate's own account/token via MCP.
            fixture=Path(__file__).with_name('verify_java_assistant.py').resolve()
            registered=client.post('/api/mcp',json={'name':'native-acceptance-fixture','transport':'stdio','command':[sys.executable,str(fixture),'--mcp-fixture','ok',str(marker)]})
            registered.raise_for_status(); mcp_id=registered.json()['id']
            assert client.post('/api/mcp/'+mcp_id+'/test').json()['ok']
            def tool(name: str,params: dict) -> dict:
                Model.action={'action':'tool','tool':name,'args':params}
                stream=events(client,'/api/assistant/chat',{'message':'授权验收专用目标，不操作其他进程或任务'})
                event=next(item for item in stream if item.get('tool')==name)
                return json.loads(event['result'])
            for _ in range(60):
                if marker.exists(): break
                time.sleep(0.05)
            pid=int(marker.read_text(encoding='utf-8'))
            assert alive(pid)
            stopped=tool('stop_process',{'pid':str(pid)})
            assert stopped['ok'], 'dedicated target stop failed: '+str(stopped)
            for _ in range(60):
                if not alive(pid): break
                time.sleep(0.05)
            assert not alive(pid)
            result['dedicated_process_terminated']=True
            try:
                outcome=tool('schedule_task',{'action':'create','name':task,'schedule':'daily 23:59','command':'cmd.exe /d /c exit 0'})
                created=bool(outcome.get('ok'))
                if created:
                    listed=tool('schedule_task',{'action':'list'})
                    assert 'OpsMate_'+task in str(listed)
                    deleted=tool('schedule_task',{'action':'delete','name':task})
                    assert deleted['ok']
                    created=False; result['task_cleanup']=True
                    listed=tool('schedule_task',{'action':'list'})
                    assert 'OpsMate_'+task not in str(listed)
                    result['task_create_list_delete']=True
                else:
                    result['task_error']='OS or tool rejected dedicated task creation; no task created'
                    result['task_cleanup']=True
            finally:
                if created:
                    cleanup=tool('schedule_task',{'action':'delete','name':task})
                    result['task_cleanup']=bool(cleanup.get('ok'))
            client.delete('/api/mcp/'+mcp_id).raise_for_status(); mcp_id=None
    finally:
        if mcp_id:
            with httpx.Client(base_url=args.url,trust_env=False,timeout=10) as cleanup:
                cleanup.delete('/api/mcp/'+mcp_id)
        model.shutdown(); model.server_close(); Model.action=None
        output=Path(__file__).resolve().parents[1]/'migration/j6/native-targets.json'
        output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result),flush=True)
    assert result['dedicated_process_terminated'] and result['task_create_list_delete'] and result['task_cleanup']


if __name__=='__main__': main()
