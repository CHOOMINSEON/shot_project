'use strict';
let planFormProject=null, planFindings=null;
const planFields={subject:'plan-subject',kind:'plan-kind',target_seconds:'plan-target',platform:'plan-platform',question:'plan-question',taste:'plan-taste',conclusion:'plan-conclusion',motive:'plan-motive',criteria:'plan-criteria',footage:'plan-footage',budget:'plan-budget',sponsorship:'plan-sponsorship',locked_script:'plan-locked-script'};
const planHeadings=['소재의 장점·단점','추천 후킹','영상 구성안','핵심 요약','썸네일·제목','캡션 요약'];
function factRow(f={}){
  const node=document.createElement('div');node.className='fact-card';
  node.innerHTML=`<label>정보 구분<select data-fact-source><option value="user">사용자 제공 사실</option><option value="external">외부 출처 · 직접 확인</option><option value="assumption">가정 · 멘트 사용 보류</option></select></label><label>항목<input data-fact-kind value="${esc(f.kind||'제품 정보')}" placeholder="가격, 구매처, 제품 표기 등"></label><label>내용<textarea data-fact-text rows="2">${esc(f.text||'')}</textarea></label><label>1차 출처 주소<input data-fact-url type="url" value="${esc(f.url||'')}"></label><label>확인 기준일<input data-fact-date type="date" value="${esc(f.checked_on||'')}"></label><label>조건<input data-fact-conditions value="${esc(f.conditions||'')}" placeholder="용량·수량·구매일·할인·배송비 등"></label><button class="danger" data-fact-remove>정보 삭제</button>`;
  node.querySelector('[data-fact-source]').value=f.source||'user';$('plan-facts').append(node);
}
function collectBrief(){
  const result={};for(const[key,id]of Object.entries(planFields))result[key]=key==='target_seconds'?($(id).value?Number($(id).value):null):$(id).value;
  result.corrections=project.state.corrections||'';
  result.facts=[...$('plan-facts').children].map(row=>({source:row.querySelector('[data-fact-source]').value,kind:row.querySelector('[data-fact-kind]').value||'제품 정보',text:row.querySelector('[data-fact-text]').value,url:row.querySelector('[data-fact-url]').value,checked_on:row.querySelector('[data-fact-date]').value,conditions:row.querySelector('[data-fact-conditions]').value})).filter(f=>f.text.trim());return result;
}
function rating(s){return `<div class="plan-rating"><b>잠정 ${s.total}/10</b><p>${s.criteria.map(c=>`${esc(c.criterion)} ${c.points}`).join(' · ')}</p><p>근거: ${esc(s.evidence)}<br>감점: ${esc(s.deduction)}<br>개선: ${esc(s.improvement)}</p></div>`;}
function planEditor(path,text,label){return `<label>${esc(label)}<textarea data-plan-path="${path}" rows="2">${esc(text)}</textarea></label>`;}
function drawPlanning(){
  if(!project)return;
  const p=project.state.planning;
  const openDetails=[...$('plan-content').children].filter(n=>n.tagName==='DETAILS').map(n=>n.open);
  if(planFormProject!==project.id){
    const brief=p?.brief||{};for(const[key,id]of Object.entries(planFields))$(id).value=brief[key]??(key==='kind'?'single':key==='platform'?'쇼츠·릴스':'');
    $('plan-facts').innerHTML='';(brief.facts||[]).forEach(factRow);planFormProject=project.id;planFindings=null;$('plan-findings').innerHTML='';
  }
  $('plan-output').classList.toggle('hidden',!p);if(!p)return;
  $('plan-download').href=`/api/projects/${project.id}/planning.md`;
  const sourceOptions=selected=>'<option value="">원본 선택</option>'+project.assets.filter(a=>a.status==='ready').map(a=>`<option value="${a.id}" ${a.id===selected?'selected':''}>${esc(a.name)}</option>`).join('');
  const actual=p.scenes.every(s=>s.asset_id&&s.source_end>s.source_start)?p.scenes.reduce((n,s)=>n+s.source_end-s.source_start,0):null;
  $('plan-content').innerHTML=`<div class="info">${esc(p.engine)}<br>목표 ${p.target_seconds}초 · 낭독 전 예상 · 실제 연결 길이 ${actual===null?'연결 전':seconds(actual)+'초'}${actual!==null&&Math.abs(actual-p.target_seconds)>.2?' · 목표와 차이가 있어요. 구간을 직접 조정해 주세요.':''}<br>점수는 초안 생성 시의 잠정 평가예요. 편집 후 실제 낭독·자료 검수를 진행해 주세요.</div>
  <details open><summary>1. 소재의 장점·단점</summary><p><b>${esc(p.subject.decision)}</b></p><p>장점: ${p.subject.pros.map(esc).join(' / ')}</p><p>단점: ${p.subject.cons.map(esc).join(' / ')}</p><p>관전 포인트: ${esc(p.subject.point)}<br>보완: ${esc(p.subject.fix)}</p>${rating(p.scores[0])}</details>
  <details><summary>2. 추천 후킹 · 서로 다른 세 가지 의문</summary><div class="hook-grid">${p.hooks.map((h,i)=>`<article class="fact-card"><b>${i+1}. ${esc(h.angle)} ${i===p.chosen_hook?'· 선택됨':''}</b>${planEditor('hooks.'+i+'.caption',h.caption,'짧은 자막')}${planEditor('hooks.'+i+'.voice',h.voice,'멘트 · 2~4초 목표')}<p>첫 1~3초: ${esc(h.shot)}</p><p>조건: ${esc(h.condition)}<br>요소: ${h.elements.map(esc).join(', ')}</p><button data-plan-hook="${i}" class="secondary" ${p.brief.locked_script?'disabled':''}>이 후킹으로 시작</button>${rating(h.score)}</article>`).join('')}</div><p>${esc(p.hook_reason)}</p>${p.brief.locked_script?'<p class="muted">확정 대본을 사용하므로 후킹을 자동 교체하지 않아요.</p>':''}${rating(p.scores[1])}</details>
  <details open><summary>3. 영상 구성안 · 실제 원본 구간 연결</summary><div class="scene-grid">${p.scenes.map((s,i)=>`<article class="scene-card"><small>예상 ${seconds(s.start)}–${seconds(s.end)}초 · 필수 컷 ${i+1}</small><b>${esc(s.role)}</b>${planEditor('scenes.'+i+'.shot',s.shot,'장면')}${planEditor('scenes.'+i+'.voice',s.voice,'녹음 멘트 · 확인 후 직접 수정')}${planEditor('scenes.'+i+'.caption',s.caption,'화면 자막 아이디어')}<label>실제 원본<select data-plan-path="scenes.${i}.asset_id">${sourceOptions(s.asset_id)}</select></label><div class="fields"><label>원본 시작(초)<input type="number" min="0" step="0.001" data-plan-path="scenes.${i}.source_start" value="${s.source_start}"></label><label>원본 종료(초)<input type="number" min="0" step="0.001" data-plan-path="scenes.${i}.source_end" value="${s.source_end}"></label></div><button data-plan-play="${i}" class="ghost">연결 구간 재생</button></article>`).join('')}</div><p>${esc(p.perspective)}</p><p class="muted">선택·축소: 인사·개봉·긴 조리 설명·단순 씹는 장면. 실제 맛 설명은 남겨주세요.</p><label>대본 합친 버전 · 표의 멘트와 동일<textarea id="plan-merged-script" rows="6" readonly>${esc(p.scenes.map(s=>s.voice).join(p.script_separator??' '))}</textarea></label><p class="muted">녹음·원본 촬영이 먼저 필요해요. 이 대본을 실제 원음 대신 자동으로 합성하거나 인식 결과로 삽입하지 않아요.</p>${rating(p.scores[2])}</details>
  <details><summary>4. 핵심 요약 · 6줄</summary>${p.summary.map(x=>`<p>${esc(x)}</p>`).join('')}${rating(p.scores[3])}</details>
  <details><summary>5. 썸네일·제목</summary><div class="hook-grid">${p.thumbnails.map((t,i)=>`<article class="fact-card">${planEditor('thumbnails.'+i+'.text',t.text,'썸네일 '+(i+1))}<p>${esc(t.image)}</p></article>`).join('')}</div>${p.titles.map((t,i)=>planEditor('titles.'+i,t,'제목 '+(i+1))).join('')}<p>추천: 썸네일 ${p.pair.thumbnail+1} + 제목 ${p.pair.title+1}<br>${esc(p.pair.reason)}</p>${rating(p.pair.score)}</details>
  <details><summary>6. 복사할 게시 캡션</summary>${planEditor('post_caption',p.post_caption,'게시 캡션')}${rating(p.scores[5])}</details>
  <details><summary>사실·출처·최종 확인</summary>${p.facts.map(f=>`<div class="fact-card"><b>${esc(f.kind)}: ${esc(f.text)}</b><p>${esc(f.status)}<br>${esc(f.checked_on||'기준일 없음')} · ${esc(f.conditions||'조건 없음')}</p>${f.url?`<a href="${esc(f.url)}" target="_blank" rel="noopener noreferrer">저장한 출처 직접 확인</a>`:''}</div>`).join('')}${p.checklist.map(x=>`<p>${esc(x)}</p>`).join('')}<p>가장 약한 항목: ${planHeadings[p.weakest]}<br>우선 수정: ${esc(p.scores[p.weakest].improvement)}</p><p>${esc(p.goal)}</p></details>`;
  [...$('plan-content').children].filter(n=>n.tagName==='DETAILS').forEach((n,i)=>{if(openDetails[i]!==undefined)n.open=openDetails[i];});
}
action('plan-add-fact',()=>factRow());
bind('plan-download','click',async e=>{e.preventDefault();requireProject();await saveQueue;await downloadSavedFile(`/api/projects/${project.id}/planning.md`,'food-short-plan.md');});
bind('plan-facts','click',e=>{if(e.target.closest('[data-fact-remove]'))e.target.closest('.fact-card').remove();});
action('plan-build',async()=>{
  requireProject();await saveQueue;const brief=collectBrief();if(!brief.subject.trim())throw Error('소재·제품명을 입력해 주세요.');
  const old=clone(project.state);project=await api('/projects/'+project.id+'/planning',{method:'POST',body:JSON.stringify({revision:project.revision,brief})});remember(old);draw();$('plan-output').scrollIntoView({behavior:'smooth',block:'start'});
});
function changePlan(path,value){return mutate(s=>{
  if(!s.planning)throw Error('기획을 먼저 만들어 주세요.');
  const p=s.planning,keys=path.split('.');let node=p;for(const key of keys.slice(0,-1))node=node[key];
  const key=keys.at(-1),previous=node[key];node[key]=value;
  // Caption ideas initially mirror finalized lines. Keep matching copies consistent after an explicit edit.
  if(keys[0]==='scenes'&&key==='voice'&&node.caption===previous.trim())node.caption=value.trim();
  if(keys[0]==='hooks'&&Number(keys[1])===p.chosen_hook&&!p.brief.locked_script){
    if(key==='voice'&&p.scenes[0].voice===previous)p.scenes[0].voice=value;
    if(key==='caption'&&p.scenes[0].caption===previous)p.scenes[0].caption=value;
  }
  p.script=p.scenes.map(scene=>scene.voice).join(p.script_separator??' ');p.edited=true;
  planFindings=null;$('plan-findings').innerHTML='문구가 바뀌었어요. 다시 검토해 주세요.';
});}
bind('plan-content','change',e=>{const path=e.target.dataset.planPath;if(path)return changePlan(path,e.target.type==='number'?Number(e.target.value):e.target.value);});
bind('plan-content','click',e=>{
  const node=e.target.closest('button');if(!node)return;
  if(node.dataset.planPlay!==undefined){const scene=project.state.planning.scenes[+node.dataset.planPlay];if(!scene.asset_id||scene.source_end<=scene.source_start)throw Error('실제 원본과 시작·종료 시간을 먼저 연결해 주세요.');activeAsset=scene.asset_id;seekSource(scene.source_start,scene.source_end);$('player').scrollIntoView({behavior:'smooth',block:'center'});}
  if(node.dataset.planHook!==undefined)return mutate(s=>{const p=s.planning,i=+node.dataset.planHook;if(p.brief.locked_script)throw Error('확정 대본은 직접 편집해 주세요.');p.chosen_hook=i;p.scenes[0].voice=p.hooks[i].voice;p.scenes[0].caption=p.hooks[i].caption;p.scenes[0].shot=p.hooks[i].shot;p.script=p.scenes.map(x=>x.voice).join(' ');p.scores[1]=clone(p.hooks[i].score);planFindings=null;$('plan-findings').innerHTML='후킹을 바꿨어요. 본편의 답과 문구를 다시 검토해 주세요.';});
});
action('plan-apply',async()=>{requireProject();await saveQueue;const old=clone(project.state);project=await api('/projects/'+project.id+'/planning/apply',{method:'POST',body:JSON.stringify({revision:project.revision})});remember(old);selected=0;currentSource=null;rendered=null;draw();toast('실제 촬영 구간으로 편집본을 구성했어요. 자막을 동기화하고 원음을 검수해 주세요.');$('player').scrollIntoView({behavior:'smooth',block:'center'});});
action('plan-edit-view',()=>$('player').scrollIntoView({behavior:'smooth',block:'center'}));
action('plan-review',async()=>{requireProject();await saveQueue;planFindings=await api('/projects/'+project.id+'/planning/review');$('plan-findings').innerHTML=`<div class="info">${esc(planFindings.notice)}</div>${planFindings.checks.map(x=>`<p class="review-note">${esc(x)}</p>`).join('')}${planFindings.fields.map((f,i)=>`<div class="fact-card"><b>${esc(f.field)}</b>${f.reasons.map(x=>`<p class="review-note">${esc(x)}</p>`).join('')}${f.suggestions.map((x,j)=>`<button data-plan-fix="${i}:${j}" class="secondary" title="${esc(x.reason)}" ${f.path?'':'disabled'}>${esc(x.before)} → ${esc(x.after)}</button>`).join('')}${!f.suggestions.length&&!f.reasons.length?'<p class="muted">등록 사전·규칙에서 문제를 찾지 못했어요. 내용·사실은 직접 대조해 주세요.</p>':''}</div>`).join('')}`;});
bind('plan-findings','click',e=>{const node=e.target.closest('[data-plan-fix]');if(!node||!planFindings)return;const[i,j]=node.dataset.planFix.split(':').map(Number),field=planFindings.fields[i];if(!field.path)return;let text=project.state.planning;for(const key of field.path.split('.'))text=text[key];return changePlan(field.path,applySuggestion(text,field.suggestions[j]));});
