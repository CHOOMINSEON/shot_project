"""Timestamped video-only scene index; silent frames remain searchable."""
import hashlib
import json
import sqlite3
from pathlib import Path

import numpy as np
from .settings import DATA
from . import scene_models

VERSION = 'scene-v1-clip32-koreanocr12'
# These English prompts are the actual inputs to the local visual/text encoder.
PROMPTS = {
 'packaging': 'a photograph of packaged food with a printed brand label',
 'product_full': 'a photograph of the whole food product on a table',
 'closeup': 'a close-up photograph of bread, pastry or other food',
 'crosssection': 'a close-up of sliced bread or pastry showing its cross section and filling',
 'cream': 'a close-up of cream filling exposed inside a pastry',
 'cutting': 'hands slicing bread or other food with a knife on a board',
 'opening': 'hands unwrapping or opening a food package',
 'holding': 'a person holding a food product up to the camera',
 'cooking': 'food being cooked in a pan or prepared in a kitchen',
 'eating': 'a person taking a bite of food, bread or a cookie',
 'comparison': 'two food products side by side for comparison',
 'reaction': 'a person showing their face after tasting food',
 'empty_space': 'a food container showing its contents and empty space',
 'size_compare': 'food next to a hand or ruler showing its size',
 'bread': 'a photograph of bread, a loaf or a bread roll',
 'cookie': 'a photograph of cookies or packaged biscuits',
 'cake': 'a photograph of cake, doughnuts or pastries',
 'drink': 'a photograph of a bottled drink or a beverage carton',
 'plain_bread': 'a photograph of plain sliced bread without any cream filling',
 'no_food_landscape': 'an outdoor landscape without food or people',
 'no_food_screen': 'a computer screen, text document or color test pattern',
 'no_food_empty': 'an empty room or plain colored background without food',
}
LABELS = {'packaging':'포장','product_full':'제품 전체','closeup':'클로즈업','crosssection':'단면',
          'cream':'크림 노출','cutting':'자르기','opening':'개봉','holding':'들기','cooking':'조리',
          'eating':'먹기·시식','comparison':'비교','reaction':'인물 반응','empty_space':'내용물·빈 공간',
          'size_compare':'크기 비교','bread':'빵','cookie':'과자','cake':'케이크·디저트','drink':'음료'}


def directory(asset_id):return DATA/'assets'/asset_id/'scenes'


def connection(asset_id):
    path=directory(asset_id);path.mkdir(parents=True,exist_ok=True)
    conn=sqlite3.connect(path/'index.sqlite',timeout=30)
    conn.row_factory=sqlite3.Row
    conn.execute('CREATE TABLE IF NOT EXISTS frames (id TEXT PRIMARY KEY,start REAL,end REAL,shot INTEGER,data TEXT,embedding BLOB)')
    conn.execute('CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY,value TEXT)')
    return conn


def fingerprint(asset):
    p=DATA/'assets'/asset['id']/'original';stat=p.stat()
    return hashlib.sha256(f'{VERSION}:{stat.st_size}:{stat.st_mtime_ns}'.encode()).hexdigest()


def load(asset_id):
    path=directory(asset_id)/'index.sqlite'
    if not path.exists():return [],None
    conn=connection(asset_id)
    try:
        rows=conn.execute('SELECT * FROM frames ORDER BY start').fetchall()
        meta={r['key']:json.loads(r['value']) for r in conn.execute('SELECT * FROM meta')}
        if not meta.get('complete'):return [],None
    finally:conn.close()
    records=[{**json.loads(r['data']),'id':r['id'],'start':r['start'],'end':r['end'],'shot':r['shot']} for r in rows]
    vectors=np.asarray([np.frombuffer(r['embedding'],dtype='<f2').astype(np.float32) for r in rows]) if rows else None
    return records,vectors


def build(asset,check=lambda:None,progress=lambda value,message:None):
    if not asset['metadata'].get('has_video',True):return {'count':0,'version':VERSION,'complete':True}
    import av
    from PIL import Image
    model=scene_models.load(check,lambda message:progress(0,message))
    keys=list(PROMPTS);text_vectors=model.texts(list(PROMPTS.values()))
    length=asset['metadata']['duration'];stamp=fingerprint(asset);folder=directory(asset['id'])
    conn=connection(asset['id'])
    try:
        meta={r['key']:json.loads(r['value']) for r in conn.execute('SELECT * FROM meta')}
        if meta.get('fingerprint')==stamp and meta.get('complete'):
            return {'count':conn.execute('SELECT COUNT(*) FROM frames').fetchone()[0],'version':VERSION,'complete':True}
        if meta.get('fingerprint')!=stamp:
            conn.execute('DELETE FROM frames');conn.execute('DELETE FROM meta');conn.commit()
            for path in folder.glob('*.jpg'):path.unlink()
        last=conn.execute('SELECT start,shot FROM frames ORDER BY start DESC LIMIT 1').fetchone()
        resume=last['start'] if last else -1
        shot=last['shot'] if last else 0
        conn.execute('INSERT OR REPLACE INTO meta VALUES (?,?)',('fingerprint',json.dumps(stamp)));conn.commit()
        previous=None;last_scan=-1;last_sample=resume;dense_until=-1;last_ocr='';last_tag=''
        previous_id=conn.execute('SELECT id FROM frames ORDER BY start DESC LIMIT 1').fetchone()
        previous_id=previous_id['id'] if previous_id else None
        observed_end=0
        source=DATA/'assets'/asset['id']/'original'
        with av.open(str(source),options={'protocol_whitelist':'file,pipe'}) as container:
            stream=container.streams.video[0];stream.codec_context.thread_count=2
            origin=float((stream.start_time or 0)*stream.time_base)
            if resume>0:container.seek(int(max(0,resume-.5+origin)/float(stream.time_base)),stream=stream)
            for frame in container.decode(stream):
                check()
                if frame.pts is None:continue
                time=float(frame.pts*frame.time_base)-origin
                if time<0 or time>length+.001:continue
                observed_end=max(observed_end,min(length,time+float(frame.duration or 1)*float(frame.time_base)))
                if time<=resume+.000001:continue
                last_scan=time
                small=frame.reformat(width=64,height=36,format='rgb24').to_ndarray().astype(np.float32)/255
                change=float(np.mean(np.abs(small-previous))) if previous is not None else 0
                cut=change>.18;previous=small
                if cut:shot+=1;dense_until=time+1
                spacing=.5 if time<dense_until else 1.
                if not cut and time-last_sample<spacing and last_sample>=0:continue
                image=frame.to_image().convert('RGB')
                rotation=asset['metadata'].get('rotation',0)
                if rotation:image=image.rotate(rotation,expand=True)
                image.thumbnail((1536,1536),Image.Resampling.LANCZOS)
                regions=scene_models.views(image)
                options=[]
                focus=['packaging','crosssection','cream','eating','cutting','cooking','bread','cookie','cake','drink']
                for region,bounds in regions:
                    check();embedding=model.image(region);values=text_vectors@embedding
                    strength=max(float(values[keys.index(k)]) for k in focus)-max(float(values[i]) for i,k in enumerate(keys) if k.startswith('no_food'))
                    options.append((strength,embedding,values,bounds))
                _,vector,scores,region_bounds=max(options,key=lambda x:x[0])
                negative=max(float(scores[i]) for i,k in enumerate(keys) if k.startswith('no_food'))
                raw={k:float(scores[i]) for i,k in enumerate(keys)}
                tags={}
                for group in [['cutting','opening','holding','cooking','eating','comparison'],['bread','cookie','cake','drink']]:
                    ordered=sorted(group,key=raw.get,reverse=True)
                    if raw[ordered[0]]>=.25 and raw[ordered[0]]-raw[ordered[1]]>=(.002 if ordered[0]=='eating' else .01) and raw[ordered[0]]-negative>=(.015 if ordered[0]=='eating' else .035):
                        tags[ordered[0]]=round(raw[ordered[0]],4)
                for key in ['packaging','product_full','closeup','crosssection','cream','reaction','empty_space','size_compare']:
                    cutoff=.285 if key in ['cream','reaction','empty_space','size_compare'] else .275 if key=='crosssection' else .26
                    if key=='cream' and (raw[key]<.285 or raw[key]-raw['plain_bread']<.02):continue
                    if raw[key]>=cutoff and raw[key]-negative>=(.015 if key=='cream' else .04):tags[key]=round(raw[key],4)
                ocr=model.read(image)[:20]
                package_vector=model.texts([PROMPTS['packaging'],PROMPTS['no_food_screen']])
                for item in ocr:
                    points=np.asarray(item['box']);x0,y0=points.min(axis=0);x1,y1=points.max(axis=0)
                    padx=max(32,(x1-x0)*.6);pady=max(32,(y1-y0)*1.5)
                    crop=image.crop((max(0,int(x0-padx)),max(0,int(y0-pady)),min(image.width,int(x1+padx)),min(image.height,int(y1+pady))))
                    local_scores=package_vector@model.image(crop)
                    item['package_region']=bool(local_scores[0]>=.25 and local_scores[0]-local_scores[1]>=.02)
                    item['package_similarity']=round(float(local_scores[0]),4)
                ocr_text=' '.join(r['text'] for r in ocr)
                top=max(tags,key=tags.get) if tags else ''
                if (ocr_text and ocr_text!=last_ocr) or top in ['crosssection','cream','eating','opening'] and top!=last_tag:
                    dense_until=time+2
                last_ocr=ocr_text;last_tag=top
                ident=f'{round(time*1000000):012d}'
                ocr_size=list(image.size)
                image.thumbnail((360,360),Image.Resampling.LANCZOS);image.save(folder/(ident+'.jpg'),quality=78)
                linked=[w for w in asset['analysis'].get('words',[]) if w['start']<time+2 and w['end']>time-.5]
                row={'asset_id':asset['id'],'filename':asset['name'],'frame_time':time,'ocr':ocr,
                     'ocr_image_size':ocr_size,'visual_region':region_bounds,'tags':tags,'similarities':{k:round(v,4) for k,v in raw.items()},'description':' · '.join(LABELS[k]+' 후보' for k in sorted(tags,key=tags.get,reverse=True)[:4]) or '시각적 내용 확인 필요',
                     'transcript':''.join(w['text'] for w in linked).strip(),
                     'uncertainties':['CLIP 태그는 후보 설명이며 제품·행동·표정의 확정 판정이 아닙니다.'],
                     'thumbnail':ident+'.jpg','scene_cut':cut}
                if previous_id:conn.execute('UPDATE frames SET end=? WHERE id=?',(time,previous_id))
                conn.execute('INSERT OR REPLACE INTO frames VALUES (?,?,?,?,?,?)',(ident,time,min(length,observed_end),shot,json.dumps(row,ensure_ascii=False),vector.astype('<f2').tobytes()))
                conn.commit();previous_id=ident;last_sample=time
                progress(min(.99,time/length),f'{asset["name"]} · {int(time)}/{int(length)}초 · 무음 포함 프레임·한국어 OCR 분석')
        if previous_id:conn.execute('UPDATE frames SET end=? WHERE id=?',(min(length,observed_end or length),previous_id))
        flag_overlays(conn)
        conn.execute('INSERT OR REPLACE INTO meta VALUES (?,?)',('complete','true'));conn.commit()
        return {'count':conn.execute('SELECT COUNT(*) FROM frames').fetchone()[0],'version':VERSION,'complete':True}
    finally:conn.close()


def protected(asset_id):
    """Conservative food-shot protection, including intervals with no speech."""
    from .timeline import merge_intervals
    records,_=load(asset_id)
    food={'packaging','product_full','closeup','crosssection','cream','eating','cutting','opening','cooking','holding','reaction'}
    return merge_intervals([[r['start'],r['end']] for r in records if food.intersection(r['tags'])])


def flag_overlays(conn):
    """Repeated small corner text is an overlay candidate, not a package identity."""
    from collections import Counter
    frames=conn.execute('SELECT id,data FROM frames').fetchall()
    counts=Counter();observed=[]
    for frame in frames:
        data=json.loads(frame['data']);w,h=data.get('ocr_image_size',[1536,864]);tokens=[]
        for text in data.get('ocr',[]):
            box=np.asarray(text['box']);x,y=box.mean(axis=0);area=np.prod(box.max(axis=0)-box.min(axis=0))/(w*h)
            token=''.join(c for c in text['text'].lower() if c.isalnum())
            corner=(x/w>.8 or x/w<.2) and (y/h<.2 or y/h>.8)
            if corner and area<.03:tokens.append(token)
        counts.update(set(tokens));observed.append((frame['id'],data,tokens))
    recurring={token for token,count in counts.items() if count>=3 and count/max(1,len(frames))>=.5}
    for ident,data,tokens in observed:
        changed=False
        for text in data.get('ocr',[]):
            token=''.join(c for c in text['text'].lower() if c.isalnum())
            if token in recurring and token in tokens:
                text.update(overlay_candidate=True,package_region=False);changed=True
        if changed:conn.execute('UPDATE frames SET data=? WHERE id=?',(json.dumps(data,ensure_ascii=False),ident))
