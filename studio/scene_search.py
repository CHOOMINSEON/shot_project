"""Evidence-led multimodal retrieval; no invented products, reactions or timestamps."""
import re
import difflib
import unicodedata
from pathlib import Path

import numpy as np
from pydantic import BaseModel, Field
from . import scene_index, scene_models
from .settings import DATA


class Product(BaseModel):
    name: str = Field(min_length=1,max_length=100)
    brand: str = Field(default='',max_length=100)
    kind: str = Field(default='',max_length=100)
    variant: str = Field(default='',max_length=100)
    aliases: list[str] = Field(default_factory=list,max_length=10)
    features: str = Field(default='',max_length=500)
    reference_ids: list[str] = Field(default_factory=list,max_length=4)


def canonical(text):return ''.join(c for c in unicodedata.normalize('NFKC',text).lower() if c.isalnum())


ACTIONS={'opening':['개봉','뜯','포장을열','봉지를열'],'holding':['들고','들어','보여','소개'],
         'cutting':['자르','잘라','칼','썰'],'cooking':['조리','굽','끓','볶','요리'],
         'eating':['먹','시식','한입','맛보'],'comparison':['비교','둘중','나란히']}
VISUAL={'packaging':['포장','패키지','로고','브랜드'],'crosssection':['단면','속을','속이','가득','내용물'],
        'cream':['크림','필링'],'closeup':['클로즈업','가까이'],'empty_space':['빈공간','양이','양은','적다'],
        'size_compare':['크기','크다','작다'],'product_full':['전체','양','가성비','가격','돈','구매']}
ABSTRACT={'expectation':['기대','궁금','과연'],'disappointment':['실망','별로','아쉽','맛없'],
          'satisfaction':['만족','맛있','좋다'],'hesitation':['고민','먹을만','살만','어떨'],
          'value':['가성비','이돈','이가격','가격값'],'repurchase':['다시사','재구매','또사']}
KINDS={'bread': ['빵','식빵','크림빵'],'cookie':['과자','쿠키','비스킷'],'cake':['케이크','도넛','디저트'],
       'drink':['음료','우유','주스','커피']}
EXPANSIONS={
 'expectation':['product_full','packaging'], 'disappointment':['eating','reaction'],
 'satisfaction':['eating','reaction'],'hesitation':['product_full','crosssection','eating'],
 'value':['product_full','packaging','crosssection','eating'],
 'repurchase':['product_full','holding'],
}
EVALUATIONS={'disappointment':['맛없','실망','아쉽','별로예','별로다','별로야','안맛있','맛있지않'],
             'satisfaction':['맛있','만족','좋아요','좋네요'],'repurchase':['재구매','다시사','또사','사먹고싶'],
             'hesitation':['고민','먹을만','살만'],'value':['가격','원','가성비','돈'],'expectation':['기대','과연','궁금']}
PERSONAL={'disappointment','satisfaction','repurchase'}



def evaluation(meaning,transcript):
    value=canonical(transcript)
    negations={
        'satisfaction':['안맛있','맛있지않','만족하지않','만족스럽지않','안만족','안좋','좋지않'],
        'disappointment':['별로아니','별로지않','맛없지않','실망하지않','아쉽지않'],
        'repurchase':['다시안사','다시사지않','다시사먹고싶지않','재구매안','재구매의사없','또사지않'],
    }
    if any(term in value for term in negations.get(meaning,[])):return False
    return any(term in value for term in EVALUATIONS[meaning])


def intent(line,products=(),previous=None):
    products=[p if isinstance(p,Product) else Product.model_validate(p) for p in products]
    text=canonical(line)
    targets=[p.model_dump() if isinstance(p,Product) else p for p in products
             if any(canonical(alias) in text for alias in [p.name,*p.aliases] if canonical(alias))]
    kind=[k for k,terms in KINDS.items() if any(t in text for t in terms)]
    actions=[k for k,terms in ACTIONS.items() if any(t in text for t in terms)]
    visual=[k for k,terms in VISUAL.items() if any(t in text for t in terms)]
    meanings=[k for k,terms in ABSTRACT.items() if any(t in text for t in terms)]
    if any(term in text for term in ['먹을만','사먹고싶','다시사','재구매']) and not any(term in text for term in ['시식','한입','먹어볼','먹는']):
        actions=[a for a in actions if a!='eating']
    inherited=False
    if not targets and previous and previous.get('products') and (actions or visual or meanings):
        targets=previous['products'];inherited=True
    if targets and not kind:
        kind=[k for k,terms in KINDS.items() if any(t in canonical(targets[0].get('kind','')) for t in terms)]
    expanded=list(dict.fromkeys(actions+visual+[tag for meaning in meanings for tag in EXPANSIONS[meaning]]))
    if not expanded:expanded=['product_full','packaging'] if targets else ['product_full']
    roles=['결론'] if 'repurchase' in meanings else ['시식 반응'] if PERSONAL.intersection(meanings) else ['비교'] if 'comparison' in actions else ['설명 근거'] if meanings or visual else ['제품 소개']
    prompts=[scene_index.PROMPTS[tag] for tag in expanded]
    # Registered appearance is a retrieval clue, never proof of product identity.
    appearance=' '.join(p.get('features','') for p in targets)
    colors={'빨강':'red','빨간':'red','노란':'yellow','노랑':'yellow','갈색':'brown','파란':'blue','초록':'green','녹색':'green','검정':'black','검은':'black','흰색':'white','하얀':'white'}
    for term,color in colors.items():
        if term in appearance:prompts.append(f'a photograph of food in {color} packaging')
    if kind:prompts += [f'a close-up photograph of {dict(bread="bread",cookie="cookies",cake="cake or doughnuts",drink="a bottled beverage")[kind[0]]}']
    return {'original':line,'products':targets,'product_kind':kind,'actions':actions,'visual_features':visual,
            'abstract_meaning':meanings,'roles':roles,'visual_queries':prompts,'expanded_tags':expanded,
            'product_from_previous_line':inherited,'personal_evaluation_required':bool(PERSONAL.intersection(meanings)) and not bool(re.search(r'까[?!.]?$',line.strip())),
            'understood':bool(targets or kind or actions or visual or meanings),'registered_visual_features':appearance}


def index_product_evidence(records,vectors,products,model,assets,check=lambda:None):
    """Exact OCR/reference evidence vs cautious temporal identity carryover."""
    refs={}
    from PIL import Image
    for p in products:
        refs[p.name]=[]
        for ident in p.reference_ids:
            path=DATA/'references'/ident/'image.jpg'
            if path.exists():
                with Image.open(path) as image:
                    refs[p.name].extend(model.image(region) for region,_ in scene_models.views(image.convert('RGB')))
    result={};anchors={}
    for number,(row,vector) in enumerate(zip(records,vectors)):
        if number%128==0:check()
        asset=assets[row['asset_id']]
        nearby=''.join(w['text'] for w in asset['analysis'].get('words',[]) if row['start']-3<w['end'] and w['start']<row['end']+1)
        visible=canonical(' '.join(o['text'] for o in row['ocr'] if o['confidence']>=.8 and not o.get('overlay_candidate')))
        spoken=canonical(nearby)
        evidence=[]
        explicit=[]
        for p in products:
            aliases=[canonical(a) for a in [p.name,*p.aliases] if canonical(a)]
            ocr_hit=any(a in visible for a in aliases)
            speech_hit=any(a in spoken for a in aliases)
            reference=max([float(np.dot(vector,r)) for r in refs[p.name]] or [0])
            variant_ok=not p.variant or canonical(p.variant) in visible
            conflict=any(q.name!=p.name and canonical(q.name) in visible for q in products)
            # Color/shape features can refine candidates, never establish identity.
            on_package=any((o.get('package_region') or 'packaging' in row['tags'] and any(kind in row['tags'] for kind in ['bread','cookie','cake','drink'])) and not o.get('overlay_candidate') for o in row['ocr'] if any(a in canonical(o['text']) for a in aliases))
            confirmed=ocr_hit and on_package and variant_ok and not conflict
            approximate=any(len(alias)>=8 and difflib.SequenceMatcher(None,alias,visible,autojunk=False).ratio()>=.9 for alias in aliases)
            confirmed=confirmed or reference>=.94 and (ocr_hit or approximate) and variant_ok and not conflict and bool(row['tags'])
            reasons=[]
            if ocr_hit:reasons.append('관측 OCR에서 제품명·별칭 확인'+(' · 포장 영역 근거 있음' if on_package else ' · 포장/자막 위치 구분 필요'))
            if speech_hit:reasons.append('주변 실제 발화에서 제품명 확인')
            if approximate and not ocr_hit:reasons.append('OCR 일부 글자 차이 · 참고 이미지와 대조 필요')
            if reference>=.75:reasons.append(f'참고 이미지 시각 유사도 {reference:.3f}')
            if reasons:
                item={'name':p.name,'status':'confirmed' if confirmed else 'candidate','reasons':reasons,
                      'uncertainties':[] if confirmed else ['OCR·제품 변형·현재 화면의 동일 제품 여부 확인 필요'],
                      'reference_similarity':round(reference,4)}
                if approximate and not ocr_hit:item['uncertainties'].append('제품 문구 OCR 일부 글자 불일치 · 참고 이미지로 보강')
                if p.variant and not variant_ok:item['uncertainties'].append('맛·제품 변형을 확인할 근거 없음')
                if conflict:item['uncertainties'].append('다른 등록 제품의 OCR 표기와 충돌')
                evidence.append(item)
                if ocr_hit or speech_hit or confirmed:explicit.append(p.name)
        if sum(p['status']=='confirmed' for p in evidence)>1:
            for item in evidence:
                if item['status']=='confirmed':
                    item['status']='candidate';item['uncertainties'].append('같은 근거로 여러 등록 제품이 겹침 · 정확한 제품·맛 구분 필요')
        if len(set(explicit))==1:
            anchors[row['asset_id']]={'name':explicit[0],'time':row['start'],'shot':row['shot'],'id':row['id']}
        elif explicit:anchors.pop(row['asset_id'],None)
        elif row.get('scene_cut'):
            # Crossing a cut is not identity evidence.
            anchors.pop(row['asset_id'],None)
        anchor=anchors.get(row['asset_id'])
        action_keys={'opening','cutting','eating','holding','crosssection','cream'}
        if not explicit and anchor and row['start']-anchor['time']<=12 and row['shot']==anchor['shot'] and action_keys.intersection(row['tags']):
            evidence.append({'name':anchor['name'],'status':'continuity_candidate','reasons':['같은 연속 숏에서 제품 소개 직후 행동·단면 후보'],
                             'anchor_frame':anchor['id'],'uncertainties':['제품명 재노출 없음 · 연속성만으로 정확한 제품·맛을 확정하지 않음']})
        result[(row['asset_id'],row['id'])]=evidence
    return result


class Search:
    def __init__(self,assets,products=(),check=lambda:None,script=''):
        self.assets=assets;self.products=[p if isinstance(p,Product) else Product.model_validate(p) for p in products]
        known={canonical(p.name) for p in self.products}
        for name in re.findall(r'["“「]([^"”」]{2,50})["”」]|([A-Za-z가-힣0-9]{2,25}(?:크림빵|빵|쿠키|비스킷|과자|우유|주스|라면|케이크|도넛))',script):
            value=next((part for part in name if part),'')
            if value and canonical(value) not in known and value not in ['첫번째빵','두번째빵','세번째빵','다른빵','이빵','저빵','그빵','크림빵','식빵']:
                self.products.append(Product(name=value));known.add(canonical(value))
        self.records=[];vectors=[]
        for asset in assets.values():
            check();rows,embeddings=scene_index.load(asset['id'])
            if embeddings is None:continue
            for row in rows:
                words=[w for w in asset['analysis'].get('words',[]) if w['start']<row['end']+1 and w['end']>row['start']-.5]
                row['transcript']=''.join(w['text'] for w in words if w.get('confidence',1)>=.5).strip()
            self.records+=rows;vectors.extend(embeddings)
        self.vectors=np.asarray(vectors,dtype=np.float32)
        self.model=scene_models.load(check) if self.records else None
        self.evidence=index_product_evidence(self.records,self.vectors,self.products,self.model,assets,check) if self.records else {}

    def query(self,line,previous=None,check=lambda:None):
        request=intent(line,self.products,previous)
        if not self.records:return {'intent':request,'exact':[],'supporting':[],'status':'정확한 일치 없음','reason':'영상 장면 인덱스가 없어요.'}
        embeddings=self.model.texts(request['visual_queries'])
        scores=np.max(self.vectors@embeddings.T,axis=1)
        requested_names={p['name'] for p in request['products']}
        boosts=np.asarray([max([.18 if p['status']=='confirmed' else .1 if p['status']=='continuity_candidate' else .05+p.get('reference_similarity',0)*.05 for p in self.evidence[(r['asset_id'],r['id'])] if p['name'] in requested_names] or [0]) for r in self.records],dtype=np.float32)
        if 'cream' in request['visual_features']:
            # Rank observed cream evidence over generic bread cross sections.
            boosts+=np.asarray([max(-.1,min(.1,(r.get('similarities',{}).get('cream',0)-r.get('similarities',{}).get('plain_bread',0))*.7)) for r in self.records])
        order=np.argsort(-(scores+boosts))[:100]
        exact=[];support=[];seen=[]
        requested_names={p['name'] for p in request['products']}
        groups={};positions={}
        for entry in self.records:
            key=(entry['asset_id'],entry['shot']);group=groups.setdefault(key,[])
            positions[(entry['asset_id'],entry['id'])]=len(group);group.append(entry)
        for index in order:
            check();row=self.records[index];score=float(scores[index])
            if score<.23:continue
            if any(a==row['asset_id'] and abs(t-row['start'])<1 for a,t in seen):continue
            seen.append((row['asset_id'],row['start']))
            actual=row['tags'];product=self.evidence[(row['asset_id'],row['id'])]
            relevant=[p for p in product if p['name'] in requested_names]
            verified=any(p['status']=='confirmed' for p in relevant)
            context=bool(relevant)
            kind_ok=not request['product_kind'] or any(k in actual for k in request['product_kind'])
            action_ok=not request['actions'] or any(k in actual for k in request['actions'])
            visual_ok=not request['visual_features'] or any(k in actual for k in request['visual_features']) or verified and set(request['visual_features'])=={'packaging'}
            transcript=canonical(row['transcript'])
            evaluations={m:evaluation(m,transcript) for m in request['abstract_meaning']}
            eval_ok=not request['personal_evaluation_required'] or all(evaluations[m] for m in request['abstract_meaning'] if m in PERSONAL)
            claim_ok=request['understood'] and kind_ok and action_ok and visual_ok and eval_ok and (not requested_names or verified)
            match_type='제품 일치' if verified and claim_ok else '의미 일치' if claim_ok and score>=(.26 if request['actions'] and action_ok else .275) and actual else '확인 필요' if context else '보조 장면'
            # A generic food image does not prove cream content, absence, personal taste or willingness to buy.
            if 'cream' in request['visual_features'] and 'cream' not in actual:match_type='보조 장면'
            if any(term in canonical(line) for term in ['가득','양이아쉽','양이적','양은적']):
                match_type='확인 필요' if context else '보조 장면'
                # Visual candidates cannot quantify 'full' or substantiate personal disappointment.
                row={**row,'uncertainties':row['uncertainties']+['내용물·양 평가를 영상만으로 확정하지 않음 · 단면 원본 확인 필요']}
            if not kind_ok and not context:continue
            if request['actions'] and not action_ok and not context:continue
            if request['abstract_meaning'] and not request['actions'] and not request['visual_features']:
                important={'product_full','packaging','holding','closeup'} if 'repurchase' in request['abstract_meaning'] else {'eating','reaction'} if PERSONAL.intersection(request['abstract_meaning']) else set(request['expanded_tags'])
                if not important.intersection(actual) and not context:continue
            if not actual and not context:continue
            if request['personal_evaluation_required'] and not eval_ok:match_type='보조 장면'
            if score<.26 and not context and not verified:continue
            uncertain=['관측 프레임 기준 구간 · 행동 시작/끝은 원본 재생으로 확인']+row['uncertainties']
            if requested_names and not verified:uncertain.append('요청한 정확한 제품 식별 근거 부족 · 같은 종류의 음식과 구분')
            if not eval_ok:uncertain.append('개인 평가·감정·재구매 발화 근거 없음 · 표정만으로 판단하지 않음')
            for p in relevant:uncertain+=p['uncertainties']
            price_text=[o['text'] for o in row['ocr'] if re.search(r'(?:[₩$€]\s*\d|\d[\d,]*\s*(?:원|won|KRW))',o['text'],re.I)]
            if 'value' in request['abstract_meaning'] and not price_text:uncertain.append('화면에서 가격 정보 확인되지 않음 · 가격·가성비를 영상만으로 입증하지 않음')
            reason=[row['description']]+[reason for p in relevant for reason in p['reasons']]
            if price_text:reason.append('관측 가격 문구: '+' / '.join(price_text))
            if evaluations and any(evaluations.values()):reason.append('근처 실제 평가 발화: '+row['transcript'])
            if match_type=='보조 장면':reason.append('문장의 의미를 직접 입증하지 않는 설명용 후보')
            ident=row['asset_id']+':'+row['id']
            neighbors=groups[(row['asset_id'],row['shot'])]
            at=positions[(row['asset_id'],row['id'])]
            before=neighbors[max(0,at-1)];after=neighbors[min(len(neighbors)-1,at+1)]
            range_start,range_end=before['start'],after['end']
            # Use neighboring observed frame boundaries, never guessed scene times.
            for neighbor,side in [(before,'start'),(after,'end')]:
                identities=self.evidence[(neighbor['asset_id'],neighbor['id'])]
                if requested_names and any(p['status']=='confirmed' and p['name'] not in requested_names for p in identities):
                    if side=='start':range_start=row['start']
                    else:range_end=row['end']
            candidate={'id':ident,'asset_id':row['asset_id'],'filename':row['filename'],'start':range_start,'end':range_end,
                       'frame_time':row['frame_time'],'match_type':match_type,'selection_reason':reason,'uncertainties':list(dict.fromkeys(uncertain)),
                       'visual_similarity':round(score,4),'products':product,'ocr':row['ocr'],'description':row['description'],
                       'transcript':row['transcript'],'thumbnail':f'/api/assets/{row["asset_id"]}/scenes/{row["id"]}.jpg',
                       'review_required':True}
            if row['end']-row['start']<1/30:continue
            if match_type in ['제품 일치','의미 일치']:exact.append(candidate)
            else:support.append(candidate)
        return {'intent':request,'exact':exact[:4],'supporting':support[:4],
                'status':'후보 확인 필요' if exact else '정확한 일치 없음',
                'reason':'모든 시각 후보는 실제 프레임과 원음을 대조한 뒤 선택하세요.'}
