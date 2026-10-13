import copy
import json
from pathlib import Path

import numpy as np
import pytest

from studio import scene_search as s, scene_index, scene_models, timeline, db
from studio.script_edit import assemble, Brief
from test_script_edit import transcript, state, cached
from test_app import upload_video, wait_job


def record(time=0,shot=0,ocr=(),tags=None,cut=False):
    return {'id':f'{int(time*1e6):012d}','asset_id':'v','filename':'실제원본.mp4','start':time,'end':time+1,'frame_time':time,
            'shot':shot,'ocr':list(ocr),'tags':tags or {'crosssection':.31},'description':'단면 후보',
            'scene_cut':cut,'uncertainties':[],'transcript':''}


class ReferenceModel:
    def image(self,image):return np.array([1.,0.])


def test_intent_expands_abstract_meaning_without_inventing_emotion():
    products=[s.Product(name='초코바나나빵',kind='빵',variant='바나나')]
    first=s.intent('초코바나나빵을 소개할게요',products)
    second=s.intent('크림이 가득하네요',products,first)
    assert second['products'][0]['name']=='초코바나나빵' and second['product_from_previous_line']
    assert {'cream','crosssection'}<=set(second['visual_features'])
    assert 'cross section' in ' '.join(second['visual_queries'])
    for line,meaning in [('기대했는데 별로다','disappointment'),('다시 사 먹고 싶다','repurchase')]:
        intent=s.intent(line);assert meaning in intent['abstract_meaning'] and intent['personal_evaluation_required']
    assert not s.intent('아무 내용 없이')['understood']
    assert not s.intent('이 돈 주고 먹을 만할까?')['actions']
    assert not s.intent('다시 사 먹고 싶다')['actions']


def test_product_identity_combines_package_text_variant_and_continuity():
    products=[s.Product(name='CU 크림빵',variant='초코'),s.Product(name='CU 딸기빵',variant='딸기')]
    label={'text':'CU 크림빵 초코','confidence':.98,'package_region':True}
    rows=[record(0,ocr=[label]),record(1,tags={'eating':.31}),record(2,shot=1,cut=True)]
    asset=transcript();asset['analysis']['words']=[]
    evidence=s.index_product_evidence(rows,np.array([[1.,0.]]*3),products,ReferenceModel(),{'v':asset})
    assert evidence[('v',rows[0]['id'])][0]['status']=='confirmed'
    assert evidence[('v',rows[1]['id'])][0]['status']=='continuity_candidate'
    assert not evidence[('v',rows[2]['id'])]
    # Color alone and a creator's text overlay cannot identify a product.
    no_package=record(ocr=[{**label,'package_region':False}])
    result=s.index_product_evidence([no_package],[[1.,0.]],products,ReferenceModel(),{'v':asset})
    assert result[('v',no_package['id'])][0]['status']=='candidate'
    wrong_flavor=record(ocr=[{**label,'text':'CU 크림빵 딸기'}])
    result=s.index_product_evidence([wrong_flavor],[[1.,0.]],products,ReferenceModel(),{'v':asset})
    assert all(e['status']!='confirmed' for e in result[('v',wrong_flavor['id'])])


def test_personal_evaluation_cannot_be_proved_by_face_or_cream_alone():
    class TextModel:
        def texts(self,prompts):return np.array([[1.,0.]]*len(prompts))
    search=s.Search.__new__(s.Search);search.products=[];search.records=[record(tags={'eating':.31,'reaction':.32})]
    search.vectors=np.array([[.31,.95]]);search.model=TextModel();search.evidence={('v',search.records[0]['id']):[]}
    for line in ['기대했는데 별로다','다시 사 먹고 싶다','크림이 가득하다']:
        result=search.query(line);assert result['status']=='정확한 일치 없음' and not result['exact']
    search.records[0]['transcript']='기대했는데 별로예요';result=search.query('기대했는데 별로다')
    assert result['exact'][0]['match_type']=='의미 일치'


def test_source_manual_caption_moves_on_reorder_and_cut():
    source=transcript();before=state();before['clips']=[{'id':'a','asset_id':'v','start':0,'end':3},{'id':'b','asset_id':'v','start':4,'end':7}]
    before['captions']={'signature':timeline.signature(before),'items':[{'id':'manual','start':.5,'end':1.5,'text':'검수한 오타 수정','edited':True}]}
    after=copy.deepcopy(before);after['clips']=[before['clips'][1],{**before['clips'][0],'start':1}]
    result=timeline.sync_captions(before,after,{'v':source})
    manual=next(c for c in result['items'] if c.get('edited'))
    assert manual['text']=='검수한 오타 수정' and manual['start']==3 and manual['end']==3.5
    assert result['signature']==timeline.signature(after) and manual['review']


def test_observed_index_partial_is_not_searchable(tmp_path,monkeypatch):
    monkeypatch.setattr(scene_index,'DATA',tmp_path)
    conn=scene_index.connection('v')
    conn.execute('INSERT INTO meta VALUES (?,?)',('complete','false'));conn.commit();conn.close()
    assert scene_index.load('v')==([],None)


def test_scene_choice_uses_stored_timestamp_and_requires_aux_review(owner,sample):
    p,asset_id=upload_video(owner,sample)
    candidate={**record(2),'id':asset_id+':000002000000','asset_id':asset_id,'match_type':'보조 장면','selection_reason':['원본 확인'], 'products':[]}
    lines=[{'line':1,'script':'단면을 보여요','status':'missing','exact':[],'supporting':[candidate]}]
    payload={'revision':p['revision'],'brief':{'script':'단면을 보여요','directions':''}}
    result={'lines':lines,'applied':False,'directing':{'supported':[],'unapplied':[]},'voice':'original','complete':False,'total':1}
    ident=db.job(p['id'],'script_edit',payload);db.update_job(ident,status='completed',result=result)
    endpoint=f'/api/projects/{p["id"]}/script-edit/{ident}/scene'
    choice={'revision':p['revision'],'line':1,'candidate_id':candidate['id']}
    assert owner.post(endpoint,json=choice).status_code==422
    response=owner.post(endpoint,json={**choice,'illustration':True});assert response.status_code==200,response.text
    updated=response.json();clip=updated['state']['clips'][0]
    assert clip['start']==2 and clip['end']==3 and updated['state']['script_edit']['complete']
    assert owner.post(endpoint,json={**choice,'illustration':True}).status_code==409
    assert owner.get(f'/api/assets/{asset_id}/scenes/../../.jpg').status_code in [404,405]


def test_korean_ocr_executes_real_model_and_word_boxes():
    from PIL import Image,ImageDraw,ImageFont
    image=Image.new('RGB',(600,200),'white')
    font=Path('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc')
    text='CU 초코 크림빵' if font.exists() else 'Nutella ORIGINAL'
    selected=ImageFont.truetype(str(font),48) if font.exists() else ImageFont.truetype('arial.ttf',48)
    ImageDraw.Draw(image).text((20,40),text,font=selected,fill='black')
    result=scene_models.load().read(image)
    assert '초코' in ''.join(r['text'] for r in result) if font.exists() else 'Nutella' in ''.join(r['text'] for r in result)
    assert all(len(r['box'])==4 and r['confidence']>=.65 for r in result)


def test_visual_protection_keeps_silent_tasting_from_automatic_cut(owner,sample,monkeypatch):
    from studio import worker
    from test_auto_cut import start
    p,asset_id=upload_video(owner,sample)
    monkeypatch.setattr(scene_index,'build',lambda *args,**kw:{'count':1,'version':scene_index.VERSION,'complete':True})
    monkeypatch.setattr(scene_index,'protected',lambda ident:[[2,4]])
    job=wait_job(owner,start(owner,p,asset_id).json()['job_id'])
    assert job['status']=='completed',job['message']
    current=owner.get('/api/projects/'+p['id']).json()
    assert current['duration']==8 and job['result']['removed_seconds']==0
    assert job['result']['protected_scenes']==1


def test_reference_image_ownership_and_product_information_validation(owner,sample):
    from PIL import Image
    import io
    p,_=upload_video(owner,sample)
    image=io.BytesIO();Image.new('RGB',(50,50),'red').save(image,'PNG')
    endpoint='/api/projects/'+p['id']
    result=owner.post(endpoint+'/product-references',content=image.getvalue(),headers={'Content-Type':'image/png'})
    assert result.status_code==200,result.text
    ref=result.json()['id'];product=s.Product(name='검수 제품',reference_ids=[ref]).model_dump()
    value=p['state'];value['scene_products']=[product]
    saved=owner.put(endpoint,json={'revision':p['revision'],'name':p['name'],'state':value});assert saved.status_code==200
    other=owner.post('/api/projects',json={'name':'다른 프로젝트'}).json()
    other['state']['scene_products']=[product]
    assert owner.put('/api/projects/'+other['id'],json={'revision':other['revision'],'name':other['name'],'state':other['state']}).status_code==422
    assert owner.post(endpoint+'/product-references',content=b'not-an-image').status_code==422


def test_repeated_creator_watermark_is_not_a_product_label(tmp_path,monkeypatch):
    monkeypatch.setattr(scene_index,'DATA',tmp_path)
    conn=scene_index.connection('v')
    for i in range(4):
        row=record(i,ocr=[{'text':'ASMR CREATOR','confidence':.99,'package_region':True,'box':[[900,10],[990,10],[990,40],[900,40]]}])
        row['ocr_image_size']=[1000,600]
        conn.execute('INSERT INTO frames VALUES (?,?,?,?,?,?)',(row['id'],i,i+1,0,json.dumps(row),np.array([1.,0.],dtype='<f2').tobytes()))
    scene_index.flag_overlays(conn);conn.commit()
    observed=json.loads(conn.execute('SELECT data FROM frames LIMIT 1').fetchone()['data'])
    assert observed['ocr'][0]['overlay_candidate'] and not observed['ocr'][0]['package_region']
    conn.close()


def test_short_insert_is_indexed_at_real_scene_change(tmp_path):
    import subprocess,shutil
    from studio.settings import DATA
    from studio.media import probe
    # Controlled 0.2s visual insert, exercising actual FFmpeg/PyAV frame timestamps.
    source=tmp_path/'short.mp4'
    subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','color=c=black:s=320x180:r=30:d=2.2',
                    '-vf',"drawbox=x=0:y=0:w=iw:h=ih:color=white:t=fill:enable='between(t,1,1.17)'",'-c:v','libx264','-threads','2',str(source)],check=True)
    ident=db.uid();target=DATA/'assets'/ident/'original';target.parent.mkdir(parents=True);shutil.copyfile(source,target)
    a={'id':ident,'name':'short-control.mp4','status':'ready','metadata':probe(target),'analysis':{}}
    scene_index.build(a);rows,_=scene_index.load(ident)
    assert any(1<=r['frame_time']<1.2 and r['scene_cut'] for r in rows)
    assert all(0<=r['start']<r['end']<=a['metadata']['duration']+.001 for r in rows)


@pytest.mark.parametrize('meaning,spoken',[('disappointment','기대했는데 맛있어요'),('satisfaction','맛있지 않아요'),('repurchase','다시 사 먹고 싶지 않아요')])
def test_personal_evaluation_checks_actual_negation(meaning,spoken):
    assert not s.evaluation(meaning,spoken)
