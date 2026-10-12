import json
import subprocess

import pytest

from studio import db, script_edit, timeline, worker
from studio.media import probe
from test_app import upload_video, wait_job


def transcript(asset_id='v', confidence=.99):
    return {'id':asset_id,'name':'원본.mp4','status':'ready','metadata':{'duration':8,'has_audio':True,'has_video':True},
            'analysis':{'transcribed':True,'words':[
                {'id':'a','text':' 과연 찾아다닐 만큼 맛있을까?','start':.5,'end':2,'confidence':confidence},
                {'id':'b','text':' 빠르게 먹어볼게요!','start':5,'end':6,'confidence':confidence}]}}


def state():
    return {'clips':[],'protections':[],'fps':30,'captions':{'items':[]}}


def cached(asset_id, words):
    analysis={'transcribed':True,'words':words}
    with db.connection() as conn:
        conn.execute('UPDATE assets SET analysis=? WHERE id=?',(json.dumps(analysis,ensure_ascii=False),asset_id))


def test_reference_order_source_words_and_directing_are_applied():
    source=transcript()
    brief=script_edit.Brief(script='빠르게 먹어볼게요!\n과연 찾아다닐 만큼 맛있을까?',directions='9:16 빠른 템포, 첫 문장 클로즈업')
    value=script_edit.assemble(brief,state(),{'v':source})
    assert value['script_brief']['script']==brief.script
    assert value['script_edit']['complete']
    assert value['clips'][0]['start']>4 and value['clips'][1]['start']<1
    assert value['clips'][0]['frame']['mode']=='fill' and value['clips'][1]['frame']['mode']=='fit'
    assert value['script_edit']['directing']['minimum']==.35
    assert value['captions']['items']==[]  # Reference text is never fabricated as recognized captions.


def test_placeholders_counts_negation_and_missing_words_are_not_guessed():
    source=transcript();source['analysis']['words']=[{'id':'a','text':'CU 세 곳에서 겨우 3개 구했어요.','start':1,'end':3,'confidence':.99},
                                                   {'id':'b','text':'달아요.','start':5,'end':6,'confidence':.99}]
    script='CU 다섯 곳에서 겨우 3개 구했어요.\n안 달아요.\n[첫 번째 제품명·실제 맛 평가]이고,\n없는 문장입니다.'
    value=script_edit.assemble(script_edit.Brief(script=script),state(),{'v':source})
    assert [r['status'] for r in value['script_edit']['lines']]==['missing','missing','placeholder','missing']
    assert value['clips']==[] and not value['script_edit']['complete']
    assert script_edit.normalized('씨유 다섯 곳, 세 개')==script_edit.normalized('CU 5곳, 3개')


def test_same_source_is_not_reused_and_short_queries_require_exact_match():
    source=transcript();source['analysis']['words']=[{'id':'a','text':'먹어볼게요!','start':1,'end':2,'confidence':.99}]
    value=script_edit.assemble(script_edit.Brief(script='먹어볼게요!\n먹어볼게요!'),state(),{'v':source})
    assert [r['status'] for r in value['script_edit']['lines']]==['matched','missing']
    value=script_edit.assemble(script_edit.Brief(script='먹어볼까요?'),state(),{'v':source})
    assert not value['clips']


def test_directing_reports_unapplied_effects_instead_of_claiming_them():
    result=script_edit.directing('빠르게, 첫 문장 클로즈업, 단면, 음악, 얼굴 추적')
    assert result['opening_close'] and result['minimum']==.35
    assert len(result['unapplied'])==3
    assert '단면' in result['unapplied'][0]
    with pytest.raises(ValueError):script_edit.Brief(script=' \n ')


def test_cached_original_script_job_applies_renders_and_undoes(owner,sample,tmp_path,monkeypatch):
    p,asset_id=upload_video(owner,sample)
    cached(asset_id,transcript()['analysis']['words'])
    monkeypatch.setattr(worker,'load_model',lambda *a:pytest.fail('Completed transcript should be reused'))
    endpoint='/api/projects/'+p['id']
    response=owner.post(endpoint+'/script-edit',json={'revision':p['revision'],'brief':{'script':'빠르게 먹어볼게요!\n과연 찾아다닐 만큼 맛있을까?','directions':'첫 문장 클로즈업'}})
    assert response.status_code==200,response.text
    job=wait_job(owner,response.json()['job_id']);assert job['status']=='completed',job['message']
    assert job['result']['complete'] and job['result']['matched']==2
    current=owner.get(endpoint).json()
    assert current['state']['clips'][0]['start']>4
    video=job['result']['files'][0];path=tmp_path/'actual.mp4'
    path.write_bytes(owner.get(f'/api/exports/{job["id"]}/{video["name"]}').content)
    assert abs(probe(path)['duration']-current['duration'])<.08
    undone=owner.post(endpoint+f'/auto-cut/{job["id"]}/undo',json={'revision':current['revision']})
    assert undone.status_code==200 and undone.json()['state']==p['state']


def test_partial_script_preview_is_labelled_and_final_export_is_blocked(owner,sample):
    p,asset_id=upload_video(owner,sample);cached(asset_id,transcript()['analysis']['words'])
    endpoint='/api/projects/'+p['id']
    job=wait_job(owner,owner.post(endpoint+'/script-edit',json={'revision':p['revision'],'brief':{'script':'빠르게 먹어볼게요!\n[실제 결론]'}}).json()['job_id'])
    assert job['status']=='completed' and not job['result']['complete'] and job['result']['files']
    current=owner.get(endpoint).json()
    response=owner.post(endpoint+'/render',json={'revision':current['revision']})
    assert response.status_code==409 and '부분 미리보기' in response.json()['detail']


def test_dubbing_upload_script_alignment_and_real_audio_replacement(owner,sample,tmp_path):
    p,video_id=upload_video(owner,sample)
    voice=tmp_path/'내_더빙.wav'
    subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','sine=frequency=880:sample_rate=48000:duration=8',str(voice)],check=True)
    data=voice.read_bytes();upload=owner.post(f'/api/projects/{p["id"]}/uploads',json={'name':voice.name,'size':len(data)}).json()
    owner.put(f'/api/uploads/{upload["id"]}/chunks/0',content=data)
    assert wait_job(owner,owner.post(f'/api/uploads/{upload["id"]}/complete').json()['job_id'])['status']=='completed'
    p=owner.get('/api/projects/'+p['id']).json()
    assert len(p['state']['clips'])==1
    audio_id=upload['id'];cached(audio_id,transcript()['analysis']['words'])
    assert owner.get(f'/api/assets/{audio_id}/thumbnail').status_code==200
    response=owner.post(f'/api/projects/{p["id"]}/script-edit',json={'revision':p['revision'],'brief':{'script':'빠르게 먹어볼게요!'},'voice_mode':'dubbing'})
    assert response.status_code==200,response.text
    job=wait_job(owner,response.json()['job_id']);assert job['status']=='completed',job['message']
    assert job['result']['voice']=='dubbing'
    current=owner.get('/api/projects/'+p['id']).json();clip=current['state']['clips'][0]
    assert clip['asset_id']==audio_id and clip['visual_asset_id']==video_id
    path=tmp_path/'dubbing-preview.mp4';file=job['result']['files'][0]
    path.write_bytes(owner.get(f'/api/exports/{job["id"]}/{file["name"]}').content)
    assert probe(path)['has_video']
    import numpy as np
    pcm=np.frombuffer(subprocess.check_output(['ffmpeg','-v','error','-i',str(path),'-t','0.5','-f','s16le','-ar','16000','-ac','1','-']),dtype='<i2')
    peak=np.argmax(abs(np.fft.rfft(pcm))) *16000/len(pcm)
    assert 875<peak<885  # Voice comes from the dubbing file, not the original 440Hz track.


def test_script_job_preserves_newer_edits_and_no_match_keeps_original(owner,sample):
    p,asset_id=upload_video(owner,sample);cached(asset_id,transcript()['analysis']['words'])
    endpoint='/api/projects/'+p['id']
    response=owner.post(endpoint+'/script-edit',json={'revision':p['revision'],'brief':{'script':'대본에만 있는 대사예요'}})
    job=wait_job(owner,response.json()['job_id'])
    assert job['status']=='completed' and not job['result']['applied']
    assert owner.get(endpoint).json()['revision']==p['revision']
    changed=owner.put(endpoint,json={'revision':p['revision'],'name':'다른 탭','state':p['state']}).json()
    ident=db.job(p['id'],'script_edit',{'revision':p['revision'],'brief':{'script':'빠르게 먹어볼게요!'},'asset_ids':[asset_id],'speech_ids':[asset_id],'voice_mode':'auto','model':'medium'})
    job=wait_job(owner,ident)
    assert job['status']=='failed' and '변경' in job['message']
    assert owner.get(endpoint).json()['revision']==changed['revision']


def test_original_and_dubbing_can_be_combined_in_one_script():
    video=transcript();video['analysis']['words']=video['analysis']['words'][:1]
    audio=transcript('voice');audio['metadata']['has_video']=False;audio['analysis']['words']=audio['analysis']['words'][1:]
    value=script_edit.assemble(script_edit.Brief(script='과연 찾아다닐 만큼 맛있을까?\n빠르게 먹어볼게요!'),state(),{'v':video,'voice':audio})
    assert value['script_edit']['complete'] and value['script_edit']['voice']=='mixed'
    assert [c['asset_id'] for c in value['clips']]==['v','voice']
    assert value['clips'][1]['visual_asset_id']=='v'


def test_dubbing_uses_corresponding_original_shot_and_honors_filename_keywords():
    video=transcript();audio=transcript('voice');audio['metadata']['has_video']=False
    brief=script_edit.Brief(script='빠르게 먹어볼게요!')
    value=script_edit.assemble(brief,state(),{'v':video,'voice':audio})
    assert value['script_edit']['voice']=='dubbing'
    assert value['clips'][0]['visual_asset_id']=='v' and value['clips'][0]['visual_start']>4
    closeup=transcript('closeup');closeup['name']='단면.mp4';closeup['analysis']['words']=[]
    brief=script_edit.Brief(script='빠르게 먹어볼게요!',directions='단면 컷을 사용')
    value=script_edit.assemble(brief,state(),{'v':video,'voice':audio,'closeup':closeup})
    assert value['clips'][0]['visual_asset_id']=='closeup'


def test_very_low_confidence_recognition_is_not_automatically_used():
    source=transcript(confidence=.2)
    value=script_edit.assemble(script_edit.Brief(script='빠르게 먹어볼게요!'),state(),{'v':source})
    assert value['clips']==[] and value['script_edit']['lines'][0]['status']=='missing'


def test_punctuation_only_lines_do_not_crash_or_match_arbitrary_footage():
    source=transcript()
    value=script_edit.assemble(script_edit.Brief(script='...\n빠르게 먹어볼게요!'),state(),{'v':source})
    assert [r['status'] for r in value['script_edit']['lines']]==['missing','matched']
    assert not value['script_edit']['complete'] and len(value['clips'])==1


def test_switching_to_dubbing_does_not_attach_another_sources_caption_edit():
    video=transcript();audio=transcript('voice');audio['metadata']['has_video']=False
    assets={'v':video,'voice':audio};brief=script_edit.Brief(script='과연 찾아다닐 만큼 맛있을까?')
    original=script_edit.assemble(brief,state(),assets,voice_mode='original')
    original['captions']=timeline.generate_captions(original,assets)
    original['captions']['items'][0].update(text='이전 원음에서만 검수한 문구',edited=True)
    dubbed=script_edit.assemble(brief,original,assets,voice_mode='dubbing')
    assert dubbed['captions']['items'][0]['text']!='이전 원음에서만 검수한 문구'
    assert dubbed['captions']['archived_edits'][0]['text']=='이전 원음에서만 검수한 문구'


def test_korean_store_and_counts_match_across_separate_asr_words_without_truncation():
    source=transcript()
    texts=['씨','유','다섯','곳이나','돌아서','겨우','세','개를','구했거든요?']
    source['analysis']['words']=[{'id':str(i),'text':' '+text,'start':i*.6,'end':(i+1)*.6,'confidence':.99} for i,text in enumerate(texts)]
    value=script_edit.assemble(script_edit.Brief(script='CU 5곳이나 돌아서 겨우 3개를 구했거든요?'),state(),{'v':source})
    assert value['script_edit']['complete'] and value['script_edit']['lines'][0]['start']==0
    assert value['script_edit']['lines'][0]['end']==pytest.approx(5.4)
    value=script_edit.assemble(script_edit.Brief(script='CU'),state(),{'v':source})
    assert value['script_edit']['lines'][0]['end']==1.2


def test_matching_is_cancellable_and_keeps_input_state_unchanged():
    from studio.media import Cancelled
    source=transcript();original=state()
    def cancel():raise Cancelled()
    with pytest.raises(Cancelled):
        script_edit.assemble(script_edit.Brief(script='빠르게 먹어볼게요!'),original,{'v':source},check=cancel)
    assert original==state()


def test_matching_does_not_hold_database_write_lock_and_rechecks_revision(owner,sample,monkeypatch):
    p,asset_id=upload_video(owner,sample);cached(asset_id,transcript()['analysis']['words'])
    assemble=script_edit.assemble
    def concurrent_edit(*args,**kwargs):
        with db.connection() as conn:
            conn.execute('UPDATE projects SET name=?,revision=revision+1 WHERE id=?',('매칭 중 다른 탭 변경',p['id']))
        return assemble(*args,**kwargs)
    monkeypatch.setattr(script_edit,'assemble',concurrent_edit)
    response=owner.post(f'/api/projects/{p["id"]}/script-edit',json={'revision':p['revision'],'brief':{'script':'빠르게 먹어볼게요!'}})
    job=wait_job(owner,response.json()['job_id'])
    assert job['status']=='failed' and '변경' in job['message']
    current=owner.get('/api/projects/'+p['id']).json()
    assert current['name']=='매칭 중 다른 탭 변경' and current['duration']==8
