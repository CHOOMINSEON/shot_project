'use strict';
// 편집 지침 기반 자동 편집 화면. app.js의 전역(project, api, poll, mutate 등)을 사용한다.
let guidedAudioSrc=new Set(),guidedAudioKey='';
let guidedDefaults=null,guidedLoading=false,guidedFormProject=null,guidedRenderKey='';
const GUIDED_REASON={prep:'촬영 준비·대기',retake:'말실수 재시도',repeat:'반복 설명',length:'목표 길이 초과',long_visual:'말 없는 장면이 김'};

async function loadGuidedDefaults(){
 if(guidedDefaults||guidedLoading)return;guidedLoading=true;
 try{guidedDefaults=await api('/guided/defaults');
  $('guided-style').innerHTML='<option value="auto">자동 추정 (업로드 구성으로 판단)</option>'+guidedDefaults.styles.map(s=>`<option value="${esc(s.key)}">${esc(s.name)}</option>`).join('');
  guidedFormProject=null;drawGuided();}
 catch(error){/* 로그인 전에는 다시 시도 */}finally{guidedLoading=false;}
}

function drawGuided(){
 if(!config||!$('guided-text'))return;
 if(!guidedDefaults){loadGuidedDefaults();return;}
 if(guidedFormProject!==project?.id){
  const saved=project?.state.guided_brief;
  $('guided-text').value=saved?.guideline||guidedDefaults.guideline;
  $('guided-style').value=saved?.style&&[...$('guided-style').options].some(o=>o.value===saved.style)?saved.style:'auto';
  guidedFormProject=project?.id;
 }
 const style=guidedDefaults.styles.find(s=>s.key===$('guided-style').value);
 $('guided-style-note').textContent=style?`${style.note} 기본 목표 ${style.target[0]}~${style.target[1]}초. 지침에 길이가 있으면 지침이 우선입니다.`:'영상 개수·말하는 비율·조리/먹는 장면 비율로 5가지 유형 중 하나를 추정합니다. 추정이 틀리면 직접 고르세요.';
 const assets=project?.assets||[];
 guidedAudioSrc=new Set([...guidedAudioSrc].filter(id=>assets.some(a=>a.id===id)));
 const srcList=assets.filter(a=>a.status==='ready'&&a.metadata.has_video!==false&&a.metadata.has_audio);
 const srcKey=srcList.map(a=>a.id+(guidedAudioSrc.has(a.id)?'1':'0')).join();
 $('guided-audio-src').classList.toggle('hidden',srcList.length<2);
 if(srcKey!==guidedAudioKey){guidedAudioKey=srcKey;$('guided-audio-list').innerHTML=srcList.map(a=>`<label class="check"><input type="checkbox" data-g-audio="${esc(a.id)}" ${guidedAudioSrc.has(a.id)?'checked':''}> ${esc(a.name)} — 화면은 쓰지 않고 소리만 사용</label>`).join('');}
 const ready=assets.some(a=>a.status==='ready'&&a.metadata.has_video!==false);
 const pending=Boolean(uploadAbort)||assets.some(a=>['uploading','checking'].includes(a.status));
 const busy=guidedStarting||[latestGuided,latestScript,latestAuto].some(j=>j&&['running','queued'].includes(j.status));
 const r=latestGuided?.result,applied=Boolean(r?.applied),current=applied&&r.render_signature===project?.render_signature;
 $('guided-start').disabled=!ready||pending||busy;
 $('guided-start').textContent=busy?'분석·자동 편집 중…':'자동 편집 시작';
 $('guided-play').classList.toggle('hidden',!current||!r?.files?.length);
 $('guided-undo').classList.toggle('hidden',!applied||project?.revision!==r.revision);
 $('guided-progress').classList.toggle('hidden',!(latestGuided&&['running','queued'].includes(latestGuided.status)));
 $('guided-progress').firstElementChild.style.width=Math.round((latestGuided?.progress||0)*100)+'%';
 const exportable=latestExport?.status==='completed'&&latestExport.result.render_signature===project?.render_signature;
 $('guided-download').disabled=!project?.state.clips.length||busy||Boolean(finalDownloading);
 $('guided-download').textContent=finalDownloading?'최종 편집본 생성 중…':exportable?'최종 편집본 다운로드':'최종 편집본 만들고 다운로드';
 if(busy&&latestGuided)$('guided-status').textContent=latestGuided.message||'자동 편집을 시작합니다.';
 else if(latestGuided&&['failed','cancelled'].includes(latestGuided.status))$('guided-status').textContent=latestGuided.message;
 else if(applied)$('guided-status').textContent=`${r.style_name} · 편집본 ${clock(r.seconds,true)} (목표 ${r.target[0]}~${r.target[1]}초)`+(r.notice?'\n'+r.notice:'');
 else if(r?.notice)$('guided-status').textContent=r.notice;
 else $('guided-status').textContent=ready?'편집 지침을 확인하고 자동 편집을 시작하세요. 음성 모델 준비 중이면 장면 분석만 먼저 사용합니다.':'왼쪽에서 촬영 원본을 올려주세요. 프로젝트는 자동으로 만들어져요.';
 $('guided-downloads').innerHTML=exportable?(latestExport.result.files||[]).filter(f=>['video','archive','subtitle'].includes(f.type)).map(f=>`<a class="button ${f.type==='video'?'primary':'secondary'}" href="/api/exports/${latestExport.id}/${encodeURIComponent(f.name)}">${{video:'MP4',archive:'ZIP(MP4·SRT·컷 목록)',subtitle:'SRT'}[f.type]} 다운로드 · ${bytes(f.size)}</a>`).join(''):'';
 const key=[latestGuided?.id,latestGuided?.updated,project?.revision].join(':');
 if(key!==guidedRenderKey){guidedRenderKey=key;$('guided-report').innerHTML=r?guidedReport(r):'';}
}

function guidedReport(r){
 const list=(items,cls='')=>items?.length?`<ul class="${cls}">${items.map(x=>`<li>${esc(x)}</li>`).join('')}</ul>`:'';
 const parts=[];
 if(r.detected)parts.push(`<p class="muted">영상 유형 자동 추정: <b>${esc(r.style_name)}</b> (${esc(r.detected.reasons.join(' · '))}). 맞지 않으면 유형을 직접 고르고 다시 실행하세요.</p>`);
 if(r.missing?.length)parts.push(`<div class="info"><b>찾지 못한 항목 (만들어 넣지 않았어요)</b>${list(r.missing)}</div>`);
 if(r.warnings?.length)parts.push(`<div class="info"><b>확인할 점</b>${list(r.warnings)}</div>`);
 if(r.moved?.length)parts.push(`<div class="info"><b>순서를 바꾼 부분</b>${list(r.moved.map(m=>`“${m.text.trim()}” — ${m.reason}`))}</div>`);
 parts.push(`<details><summary>적용한 지침 ${r.applied.length}개 · 자동 적용하지 않은 지침 ${r.unapplied.length}개</summary>${list(r.applied)}${r.unapplied.length?'<b>적용하지 않음</b>'+list(r.unapplied):''}</details>`);
 const need=(r.units||[]).filter(u=>u.status==='확인 필요').length;
 parts.push(`<details open><summary>추천 구간 ${r.units.length}개 · 확인 필요 ${need}개</summary>${(r.units||[]).map(u=>`<div class="script-row ${u.status==='확인 필요'?'missing':'matched'}"><b>${esc(u.role_label)} · ${esc(u.status)}</b>${u.text?`<p>${esc(u.text.trim())}</p>`:''}<small>${esc(u.filename)} · ${clock(u.start,true)}–${clock(u.end,true)} · ${esc(u.reason)}</small>${u.product?`<small> · 제품: ${esc(u.product.name)} (${esc(u.product.status==='confirmed'?'OCR·발화 근거':'확인 필요')})</small>`:''}${u.review?.length?`<p class="review-note">${esc(u.review.join(' · '))}</p>`:''}${u.product?.status==='확인 필요'&&u.product.uncertain?.length?`<p class="review-note">${esc(u.product.uncertain.join(' · '))}</p>`:''}<button class="secondary" data-g-play="${esc(u.asset_id)}" data-g-start="${u.start}" data-g-end="${u.end}">원본 구간 재생</button></div>`).join('')}</details>`);
 parts.push(`<details><summary>삭제한 구간 ${r.removed.length}개 (이유 확인·복원)</summary>${r.removed.map((x,i)=>`<div class="script-row"><b>${esc(GUIDED_REASON[x.reason_code]||x.reason_code)}</b><small>${esc(x.filename)} · ${clock(x.start,true)}–${clock(x.end,true)} · ${esc(x.reason)}</small>${x.text?`<p>${esc(x.text.trim())}</p>`:''}<div class="button-row"><button class="secondary" data-g-play="${esc(x.asset_id)}" data-g-start="${x.start}" data-g-end="${x.end}">재생</button><button class="ghost" data-g-restore="${i}">복원</button></div></div>`).join('')||'<p class="muted">삭제한 구간이 없어요.</p>'}</details>`);
 if(r.narration_expected||r.narration?.length)parts.push(guidedNarration(r));
 return parts.join('');
}

function guidedNarration(r){
 const lines=r.narration||[];
 if(!lines.length)return '<div class="info"><b>나레이션</b><p>이 유형은 후녹음 나레이션을 많이 쓰지만 나레이션 음성 파일이 없어요. 녹음한 파일을 올린 뒤 다시 실행하면 문장별로 어울리는 장면을 추천합니다. 아래 타임라인의 원음 클립은 촬영 소리 그대로예요.</p></div>';
 const done=lines.filter(l=>l.status==='linked').length;
 const cards=l=>l.status==='linked'?`<p class="muted">연결 완료 · ${esc(project.assets.find(a=>a.id===l.linked.asset_id)?.name||'')} ${clock(l.linked.start,true)}–${clock(l.linked.end,true)}</p>`
  :(l.suggestions.length?l.suggestions.map(c=>`<article class="scene-candidate"><img loading="lazy" src="${esc(c.thumbnail)}" alt=""><div><b>${esc(c.match_type)} · ${esc(c.filename)}</b><p>${clock(c.start,true)}–${clock(c.end,true)}</p><p>${esc(c.selection_reason.join(' · '))}</p><p class="review-note">${esc(c.uncertainties.join(' · '))}</p><div class="button-row"><button class="secondary" data-g-play="${esc(c.asset_id)}" data-g-start="${c.start}" data-g-end="${c.end}">원본 구간 재생</button><button class="primary" data-g-link="${l.index}" data-g-cand="${esc(c.id)}">이 장면에 연결</button></div></div></article>`).join(''):'<p class="review-note">추천할 장면을 찾지 못했어요. 아래에서 시간을 직접 지정하세요.</p>');
 const options=(project.assets||[]).filter(a=>a.metadata.has_video!==false&&!guidedAudioSrc.has(a.id)).map(a=>`<option value="${esc(a.id)}">${esc(a.name)}</option>`).join('');
 return `<details open><summary>나레이션 ${lines.length}문장 · 연결 ${done}/${lines.length}</summary><p class="muted">나레이션은 추천만 하고 자동으로 붙이지 않아요. 원본을 재생해 확인한 뒤 연결하세요.</p>${lines.map(l=>`<div class="script-row ${l.status==='linked'?'matched':'missing'}"><b>${l.index+1}. ${l.status==='linked'?'연결됨':'장면 선택 필요'}</b><p>${esc(l.text.trim())}</p>${cards(l)}</div>`).join('')}<div class="script-row"><b>직접 지정</b><div class="fields three"><label>문장 번호<input id="g-line" type="number" min="1" max="${lines.length}" value="1"></label><label>영상<select id="g-asset">${options}</select></label><label>시작(초)<input id="g-start" type="number" min="0" step="0.01" value="0"></label><label>종료(초)<input id="g-end" type="number" min="0" step="0.01" value="3"></label></div><button class="secondary" id="g-manual">이 구간에 연결</button></div></details>`;
}

action('guided-start',async()=>{
 requireProject();await saveQueue;
 const guideline=$('guided-text').value.trim(),style=$('guided-style').value,frame=$('guided-frame').value;
 guidedStarting=true;drawGuided();
 try{await mutate(s=>{s.guided_brief={guideline,style};});
  await api('/projects/'+project.id+'/guided-edit',{method:'POST',body:JSON.stringify({revision:project.revision,guideline,style,frame,audio_source_ids:[...guidedAudioSrc]})});
  await poll();}
 finally{guidedStarting=false;drawGuided();}
});
bind('guided-style','change',drawGuided);
action('guided-play',()=>{
 const r=latestGuided?.result,video=r?.files?.find(f=>f.type==='video');
 if(video&&r.render_signature===project.render_signature){rendered=latestGuided.id;mode='edited';setSource('/api/exports/'+rendered+'/'+encodeURIComponent(video.name)+'?inline=true',0,true);$('preview-label').textContent='지침 자동 편집 추천본 · 미리보기 화질';}
});
action('guided-download',async()=>{
 requireProject();await saveQueue;
 if(latestExport?.status==='completed'&&latestExport.result.render_signature===project.render_signature){await saveFinalVideo(latestExport);return;}
 const response=await api('/projects/'+project.id+'/render',{method:'POST',body:JSON.stringify({revision:project.revision,mode:'full',preview:false,filename:'최종_편집본'})});
 finalDownloading=response.job_id;drawGuided();await poll();toast('최종 MP4를 만들고 있습니다. 완료되면 다운로드를 시작합니다.');
});
action('guided-captions',()=>{const box=$('advanced-edit');box.open=true;document.querySelector('[data-tab="captions"]')?.click();box.scrollIntoView({behavior:'smooth'});});
action('guided-undo',async()=>{
 await saveQueue;const old=clone(project.state);
 project=await api('/projects/'+project.id+'/auto-cut/'+latestGuided.id+'/undo',{method:'POST',body:JSON.stringify({revision:project.revision})});
 remember(old);rendered=null;currentSource=null;draw();toast('지침 자동 편집 전 타임라인으로 되돌렸어요.');
});
bind('guided-report','click',async e=>{
 const b=e.target.closest('button');if(!b)return;
 const r=latestGuided?.result;
 if(b.dataset.gPlay){scenePreviewEnd=+b.dataset.gEnd;mode='source';setSource('/api/assets/'+b.dataset.gPlay+'/video',+b.dataset.gStart,true);$('preview-label').textContent='원본 확인 · '+clock(+b.dataset.gStart,true)+'–'+clock(scenePreviewEnd,true);}
 if(b.dataset.gRestore!==undefined){
  const x=r.removed[+b.dataset.gRestore];
  await mutate(s=>{const frame=clone((s.clips.find(c=>c.asset_id===x.asset_id)||s.clips[0]||{}).frame||{mode:'fit',x:.5,y:.5,zoom:1});
   const item={id:uuid(),asset_id:x.asset_id,start:x.start,end:x.end,label:'복원 · '+x.reason,frame};
   const at=s.clips.findIndex(c=>c.asset_id===x.asset_id&&!c.visual_asset_id&&c.start>=x.end-.001);
   if(at<0)s.clips.push(item);else s.clips.splice(at,0,item);});
  rendered=null;currentSource=null;toast('삭제했던 구간을 타임라인에 복원했어요. 렌더 미리보기를 다시 만들어 확인하세요.');
 }
 if(b.dataset.gLink!==undefined)await linkNarration(+b.dataset.gLink,{candidate_id:b.dataset.gCand});
});
bind('guided-report','click',async e=>{
 if(e.target.id!=='g-manual')return;
 const line=(+$('g-line').value||1)-1;
 await linkNarration(line,{asset_id:$('g-asset').value,start:+$('g-start').value,end:+$('g-end').value});
});
async function linkNarration(line,choice){
 await saveQueue;const previous=clone(project.state);
 project=await api(`/projects/${project.id}/guided-edit/${latestGuided.id}/narration`,{method:'POST',body:JSON.stringify({revision:project.revision,line,...choice})});
 remember(previous);rendered=null;currentSource=null;scenePreviewEnd=null;selected=0;draw();await poll();toast('확인한 장면에 나레이션을 연결했어요. 렌더 미리보기로 소리와 화면을 확인하세요.');
}

document.addEventListener('change',event=>{
 const box=event.target.closest?.('[data-g-audio]');
 if(!box)return;
 if(box.checked)guidedAudioSrc.add(box.dataset.gAudio);else guidedAudioSrc.delete(box.dataset.gAudio);
 guidedAudioKey='';drawGuided();
});
