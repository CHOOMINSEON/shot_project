'use strict';
const $ = id => document.getElementById(id);
const esc = text => String(text ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const clone = x => structuredClone(x);
const uuid = () => crypto.randomUUID();
const seconds = n => Number(n).toFixed(2);
const clock = (value, millis=false) => {value=Math.max(0,Number(value)||0);const h=Math.floor(value/3600),m=Math.floor(value/60)%60,s=Math.floor(value)%60;return `${h ? String(h).padStart(2,'0')+':' : ''}${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}${millis?'.'+String(Math.floor(value*1000)%1000).padStart(3,'0'):''}`;};
const bytes = n => n >= 1e9 ? `${(n/1e9).toFixed(2)} GB` : `${(n/1e6).toFixed(1)} MB`;
let project=null, config=null, selected=0, activeAsset=null, history=[], future=[], saveQueue=Promise.resolve(), saving=0;
let mode='edited', rendered=null, currentJobIds=new Map(), pollTimer=null, uploadAbort=null, uploadPaused=false;
let contextEnd=null, currentSource=null, pendingSeek=null;
let desktopTimer=null, latestAuto=null, latestExport=null, quickStarting=false, latestScript=null, scriptStarting=false, scriptFormProject=null;
const captionFindings=new Map();
function toast(message){$('toast').textContent=message;$('toast').style.display='block';clearTimeout(toast.timer);toast.timer=setTimeout(()=>$('toast').style.display='none',6000);}
async function api(path, options={}){
  const response=await fetch('/api'+path,{...options,headers:{...(options.body && typeof options.body==='string'?{'Content-Type':'application/json'}:{}),...options.headers}});
  if(response.status===401 && path!='/login'){$('login-dialog').showModal();throw Error('소유자 로그인이 필요합니다.');}
  const data=await response.json().catch(()=>({}));
  if(!response.ok)throw Error(typeof data.detail==='string'?data.detail:(data.detail?.[0]?.msg||'요청을 처리하지 못했습니다. 입력과 연결 상태를 확인해 주세요.'));
  return data;
}
function bind(id, event, action){$(id).addEventListener(event,e=>{try{Promise.resolve(action(e)).catch(error=>toast(error.message));}catch(error){toast(error.message);}});}
function action(id, fn){bind(id,'click',fn);}
function requireProject(){if(!project)throw Error('먼저 프로젝트를 만들거나 선택해 주세요.');return project;}
function clip(){return project?.state.clips[selected];}
function asset(){return project?.assets.find(a=>a.id===activeAsset);}
function editedLength(state=project?.state){return (state?.clips||[]).reduce((n,c)=>n+c.end-c.start,0);}
function captionSynced(){return project?.state.captions?.signature===project?.signature;}
function selectedOffset(){return (project?.state.clips||[]).slice(0,selected).reduce((n,c)=>n+c.end-c.start,0);}
function editedPosition(){if(rendered)return $('player').currentTime;return mode==='source'?$('player').currentTime:Math.max(0,selectedOffset()+$('player').currentTime-(clip()?.start||0));}

async function loadProjects(preferred){const list=await api('/projects');$('projects').innerHTML='<option value="">프로젝트 선택</option>'+list.map(p=>`<option value="${p.id}">${esc(p.name)}</option>`).join('');const id=preferred||list[0]?.id;if(id){$('projects').value=id;await loadProject(id);}}
async function loadProject(id){planFormProject=null;captionFindings.clear();$('player').pause();rendered=null;currentSource=null;project=await api('/projects/'+id);selected=0;activeAsset=project.assets.find(a=>a.status==='ready')?.id||project.assets[0]?.id;history=[];future=[];currentJobIds=new Map();latestAuto=null;latestExport=null;latestScript=null;scriptFormProject=null;draw();await poll();}
function remember(state){history.push(clone(state));if(history.length>40)history.shift();future=[];}
function mutate(fn, track=true){
  saving++;
  const task=saveQueue.catch(()=>{}).then(async()=>{
    requireProject();const old=clone(project.state), next=clone(project.state);fn(next);
    $('save-status').textContent='저장 중…';
    try{const result=await api('/projects/'+project.id,{method:'PUT',body:JSON.stringify({revision:project.revision,state:next,name:$('project-name').value.trim()||project.name})});if(track)remember(old);project=result;rendered=null;draw();}
    catch(error){localStorage.setItem('studio-recovery-'+project.id,JSON.stringify(next));if(error.message.includes('변경되었')){project=await api('/projects/'+project.id);draw();}throw error;}
  });
  saveQueue=task.finally(()=>{saving--;});return saveQueue;
}
function draw(){
  if(!project)return;
  selected=Math.max(0,Math.min(selected,project.state.clips.length-1));
  if(!project.assets.some(a=>a.id===activeAsset))activeAsset=project.assets[0]?.id;
  $('project-name').value=project.name;$('workspace-name').textContent=project.name;
  $('save-status').textContent=`✓ 저장됨 · 편집 버전 ${project.revision}`;$('asset-count').textContent=project.assets.length+'개';
  $('assets').innerHTML=project.assets.map(a=>`<div class="asset ${a.id===activeAsset?'active':''}" data-asset="${a.id}">${a.status==='ready'?`<img src="/api/assets/${a.id}/thumbnail" alt="">`:'<span>◷</span>'}<div><b title="${esc(a.name)}">${esc(a.name)}</b><small>${bytes(a.size)} · ${a.status==='ready'?clock(a.metadata.duration):({'uploading':'업로드 대기','checking':'영상 검사 중','invalid':'파일 검사 실패'}[a.status]||a.status)}</small></div>${['uploading','invalid'].includes(a.status)?`<button data-discard="${a.id}" class="danger">정리</button>`:''}</div>`).join('')||'<div class="empty-small">원본을 올리면 여기에 모여요.</div>';
  $('analysis-asset').innerHTML=project.assets.filter(a=>a.status==='ready').map(a=>`<option value="${a.id}">${esc(a.name)}</option>`).join('');$('analysis-asset').value=activeAsset||'';
  $('vocabulary').value=project.state.vocabulary||'';$('reference-script').value=project.state.reference_script||'';$('fps').value=project.state.fps||30;$('quality').value=project.state.quality||'standard';
  const length=editedLength();$('total-time').textContent=clock(length);$('export-duration').textContent=clock(length);$('timeline-end').textContent=clock(length);$('timeline-mid').textContent=clock(length/2);$('clip-count').textContent=`${project.state.clips.length}개 구간`;
  $('timeline-track').innerHTML=project.state.clips.map((c,i)=>`<button class="timeline-clip ${i===selected?'active':''}" data-clip="${i}" style="flex:${Math.max(1,(c.end-c.start)/5)}" title="${esc(c.label)} · ${clock(c.start)}–${clock(c.end)}">${esc(c.label||'유지 구간')} <small>${clock(c.end-c.start)}</small></button>`).join('')||'<span class="muted">유지 구간을 추가하면 편집 타임라인이 생겨요.</span>';
  $('undo').disabled=!history.length;$('redo').disabled=!future.length;drawClip();drawAnalysis();drawCaptions();drawPlanning();waveform();
  drawQuick();drawScript();
  $('srt-download').href=project?`/api/projects/${project.id}/captions.srt`:'#';
  if(!currentSource && clip())selectClip(selected,false);
}
function drawClip(){const c=clip();$('clip-editor').classList.toggle('hidden',!c);if(!c)return;$('clip-label').value=c.label||'';$('clip-start').value=seconds(c.start);$('clip-end').value=seconds(c.end);$('protect-start').value=seconds(c.start);$('protect-end').value=seconds(c.end);const frame=c.frame||{};$('frame-mode').value=frame.mode||'fit';$('frame-x').value=frame.x??.5;$('frame-y').value=frame.y??.5;$('frame-zoom').value=frame.zoom??1;$('zoom-value').textContent=(frame.zoom||1)+'×';applyFrame();}
function candidates(){const a=asset();if(a?.analysis.silence){return a.analysis.silence.gaps.map(([a,b])=>({start:a+(a>.001?+$('post-roll').value:0),end:b-(b<asset().metadata.duration-.001?+$('pre-roll').value:0),length:b-a})).filter(g=>g.length>=+$('min-gap').value&&g.end>g.start);}if(!a?.analysis.speech)return[];const minimum=+$('min-gap').value,before=+$('pre-roll').value,after=+$('post-roll').value;let cursor=0;const result=[];for(const [start,end]of [...a.analysis.speech,[a.metadata.duration,a.metadata.duration]]){if(start-cursor>=minimum){const x=Math.max(0,cursor+(cursor?after:0)),y=Math.max(0,start-(start<a.metadata.duration?before:0));if(y>x)result.push({start:x,end:y});}cursor=Math.max(cursor,end);}return result;}
function drawAnalysis(){const a=asset();const gaps=candidates();$('candidate-count').textContent=gaps.length;$('candidates').innerHTML=gaps.map((g,i)=>`<div class="candidate"><input type="checkbox" data-gap="${i}" aria-label="공백 후보 ${i+1} 선택" checked><span>${clock(g.start)} → ${clock(g.end)}<small>${seconds(g.end-g.start)}초 · ${cutState(g,a?.id)}</small></span><button data-context="${i}">앞뒤 재생</button><button data-restore-gap="${i}">복원</button></div>`).join('')||'<p class="muted">분석 전이거나 현재 설정에 맞는 공백 후보가 없어요.</p>';
  $('protections').innerHTML=(project.state.protections||[]).map((p,i)=>`<div class="protection">🛡 ${esc(project.assets.find(a=>a.id===p.asset_id)?.name||'원본')} ${clock(p.start)}–${clock(p.end)}<button class="ghost" data-unprotect="${i}">해제</button></div>`).join('');
  $('products').innerHTML=(a?.analysis.products||[]).map((p,i)=>`<div class="product"><b>${esc(p.name)}</b> <small>확인 필요</small><p>${esc(p.text)}</p><small>${clock(p.start)}–${clock(p.end)}</small><div class="button-row"><button data-product="${i}" class="ghost">재생</button><button data-product-add="${i}" class="secondary">유지 구간으로 추가</button></div></div>`).join('')||'<p class="muted">음성 인식 후 제품 전환 후보가 표시돼요.</p>';
  $('transcript').innerHTML=(a?.analysis.words||[]).map(w=>`<button class="transcript-word ${w.review?'review':''}" data-word="${w.start}" title="${clock(w.start)}${w.review?' · 확인 필요':''}">${esc(w.text)}</button>`).join('')||'<p class="muted">음성 인식 결과가 아직 없어요.</p>';
  if(a?.metadata){const m=a.metadata;$('media-info').innerHTML=`원본 ${m.width||'—'} × ${m.height||'—'}<br>회전 ${m.rotation||0}° · ${esc(m.fps||'—')} fps<br>영상 ${esc(m.codec||'—')} · 오디오 ${esc(m.sample_rate||'없음')} Hz<br>${esc(m.transfer||'—')} / ${esc(m.primaries||'—')}<br>${esc(m.hdr_warning||'')}`;}
}
function cutState(g,assetId){const preserved=project.state.protections.some(p=>p.asset_id===assetId&&p.start<g.end&&p.end>g.start);const remains=project.state.clips.some(c=>c.asset_id===assetId&&c.start<g.end&&c.end>g.start);return preserved?'보존 구간 포함':remains?'검토 대기':'컷 적용됨';}
function suggestionButtons(result, attribute){return (result?.suggestions||[]).map((x,i)=>`<button ${attribute}="${i}" class="secondary" title="${esc(x.reason)}">${esc(x.before)} → ${esc(x.after)}</button>`).join('');}
function applySuggestion(text,suggestion){const letters=Array.from(text);if(letters.slice(suggestion.start,suggestion.end).join('')!==suggestion.before)throw Error('문구가 바뀌었어요. 다시 검토해 주세요.');return letters.slice(0,suggestion.start).join('')+suggestion.after+letters.slice(suggestion.end).join('');}
async function downloadSavedFile(url,filename){
  const response=await fetch(url);if(!response.ok){const result=await response.json().catch(()=>({}));throw Error(result.detail||'다운로드를 준비하지 못했어요.');}
  const objectURL=URL.createObjectURL(await response.blob()),anchor=document.createElement('a');anchor.href=objectURL;anchor.download=filename;anchor.click();setTimeout(()=>URL.revokeObjectURL(objectURL),1000);
}
function drawCaptions(){
  const caption=project.state.captions||{},items=caption.items||[],pending=items.filter(c=>c.text.trim()&&!c.reviewed).length;
  $('corrections').value=project.state.corrections||'';
  $('caption-status').textContent=captionSynced()?`✓ 타임라인 동기화 · ${items.length}개 자막 · 미검수 ${pending}개`:(items.length?'컷이 바뀌었어요. 자막을 다시 생성하고 문구와 시간을 확인해 주세요.':'음성 인식 후 생성하거나 직접 자막을 추가할 수 있어요.');
  $('caption-list').innerHTML=items.map((c,i)=>{const finding=captionFindings.get(c.id);return `<div class="caption-card ${c.reviewed?'approved':''}"><small>${c.reviewed?'✓ 검수 완료':'검수 대기'} · 자막 ${i+1}</small>${c.source_text?`<details><summary>인식 원문 · 참고 신뢰값 ${Number(c.confidence||0).toFixed(2)}</summary><p>${esc(c.source_text)}</p></details>`:'<p class="muted">직접 입력한 자막 · 실제 음성과 대조해 주세요.</p>'}<textarea data-caption-text="${i}" aria-label="자막 ${i+1} 문구">${esc(c.text)}</textarea>${(c.review_reasons||[]).map(x=>`<p class="review-note">${esc(x)}</p>`).join('')}<div class="fields"><label>편집본 시작(초)<input type="number" step="0.001" min="0" data-caption-start="${i}" value="${c.start}"></label><label>편집본 종료(초)<input type="number" step="0.001" min="0" data-caption-end="${i}" value="${c.end}"></label></div><div class="button-row"><button data-caption-play="${i}" class="ghost">앞뒤 재생</button>${c.source_asset_id?`<button data-caption-source="${i}" class="ghost">원음 대조</button>`:''}<button data-caption-inspect="${i}" class="secondary">문구 검토</button><button data-caption-approve="${i}" class="small-primary">검수 완료</button></div>${finding?`<div class="review-findings">${finding.reasons.map(x=>`<p>${esc(x)}</p>`).join('')}<div class="button-row">${suggestionButtons(finding,'data-caption-suggestion')}</div><p class="muted">${finding.suggestions.length?'제안을 선택하면 해당 표기만 바꾸고 재검수 상태로 전환해요.':'등록 사전·맞춤법 규칙에서 수정 제안을 찾지 못했어요. 원음과 사실은 직접 확인해 주세요.'}</p></div>`:''}<div class="button-row"><button data-caption-split="${i}" class="ghost">나누기</button><button data-caption-merge="${i}" class="ghost">다음과 합치기</button><button data-caption-delete="${i}" class="danger">자막만 삭제</button></div></div>`;}).join('');
  $('caption-archive').innerHTML=(caption.archived_edits||[]).map(c=>`<div class="caption-card"><small>${esc(c.archive_reason)}</small><textarea readonly aria-label="이전 수정 문구">${esc(c.text)}</textarea><p class="muted">편집본 ${clock(c.start)}–${clock(c.end)} · 자동 대응하지 못해 보관했어요. 필요한 문구를 새 자막에 복사해 주세요.</p></div>`).join('')||'<p class="muted">보관된 이전 수정 자막이 없어요.</p>';
}

function applyFrame(){const frame=clip()?.frame||{};const player=$('player');player.style.transform='none';$('background-video').style.display='none';if(rendered){player.style.objectFit='contain';return;}player.style.objectFit=frame.mode==='fill'?'cover':'contain';player.style.objectPosition=`${(frame.x??.5)*100}% ${(frame.y??.5)*100}%`;if(frame.mode==='fill')player.style.transform=`scale(${frame.zoom||1})`;if(frame.mode==='blur')$('background-video').style.display='block';}
function waveform(){const canvas=$('waveform'),ctx=canvas.getContext('2d');canvas.width=canvas.clientWidth*devicePixelRatio;canvas.height=44*devicePixelRatio;ctx.clearRect(0,0,canvas.width,canvas.height);const peaks=asset()?.analysis.peaks||[];ctx.fillStyle='#a3a3a3';const count=Math.floor(canvas.width/4);for(let i=0;i<count;i++){let peak=0;const a=Math.floor(i/count*peaks.length),b=Math.max(a+1,Math.floor((i+1)/count*peaks.length));for(let j=a;j<b;j++)peak=Math.max(peak,peaks[j]||0);const h=peak*canvas.height*.9;ctx.fillRect(i*4,(canvas.height-h)/2,2,Math.max(1,h));}}

function setSource(url,time=0,play=false){const player=$('player');contextEnd=null;$('video-empty').classList.add('hidden');$('video-warning').classList.add('hidden');pendingSeek={time,play};if(currentSource!==url){player.pause();currentSource=url;player.src=url;$('background-video').src=url;}else if(player.readyState>=1){player.currentTime=time;pendingSeek=null;if(play)player.play().catch(()=>{});}applyFrame();}
bind('player','loadedmetadata',()=>{if(pendingSeek){const{time,play}=pendingSeek;pendingSeek=null;$('player').currentTime=time;if(play)$('player').play().catch(()=>{});}});
function selectClip(index,play=false){if(!project.state.clips[index])return;selected=index;activeAsset=clip().asset_id;rendered=null;mode='edited';$('edited-view').classList.add('active');$('source-view').classList.remove('active');$('preview-label').textContent='원본 기반 구간 미리보기 · HDR 색은 렌더로 확인';setSource('/api/assets/'+activeAsset+'/video',clip().start,play);drawClip();drawAnalysis();waveform();document.querySelectorAll('[data-clip]').forEach(b=>b.classList.toggle('active',+b.dataset.clip===index));}
function seekEdited(time,play=false){if(rendered){$('player').currentTime=time;if(play)$('player').play();return;}let offset=0;for(let i=0;i<project.state.clips.length;i++){const c=project.state.clips[i],length=c.end-c.start;if(time<offset+length||i===project.state.clips.length-1){selectClip(i,false);setSource('/api/assets/'+c.asset_id+'/video',c.start+Math.min(length,Math.max(0,time-offset)),play);break;}offset+=length;}}
function seekSource(time,end=null){if(!asset()||asset().status!=='ready')return;rendered=null;mode='source';$('source-view').classList.add('active');$('edited-view').classList.remove('active');setSource('/api/assets/'+activeAsset+'/video',time,true);contextEnd=end;$('preview-label').textContent='원본 시간 기준 미리보기';}
bind('player','timeupdate',()=>{const player=$('player');if(contextEnd!==null&&player.currentTime>=contextEnd){player.pause();contextEnd=null;}if(!rendered&&mode==='edited'&&clip()&&player.currentTime>=clip().end-.025){if(!player.paused&&selected<project.state.clips.length-1)selectClip(selected+1,true);else player.pause();}const t=editedPosition();$('playhead').textContent=clock(t,true);$('scrub').max=rendered?player.duration||1:(mode==='source'?asset()?.metadata.duration||1:editedLength()||1);$('scrub').value=t;const cap=captionSynced()?project.state.captions.items.find(c=>c.start<=t&&c.end>t):null;$('caption-overlay').textContent=$('show-captions').checked&&mode==='edited'?cap?.text||'':'';if(!$('background-video').paused&&Math.abs($('background-video').currentTime-player.currentTime)>.25)$('background-video').currentTime=player.currentTime;});
bind('player','play',()=>{$('play').textContent='Ⅱ';const bg=$('background-video');bg.currentTime=$('player').currentTime;bg.play().catch(()=>{});});bind('player','pause',()=>{$('play').textContent='▶';$('background-video').pause();});bind('player','error',()=>{$('video-warning').classList.remove('hidden');$('video-warning').textContent='이 브라우저에서 원본 코덱을 재생하지 못합니다. 렌더 미리보기를 만들면 H.264로 확인할 수 있어요.';});
action('play',()=>{if(!$('player').src)throw Error('원본을 먼저 올려주세요.');$('player').paused?$('player').play():$('player').pause();});bind('scrub','input',()=>mode==='source'?$('player').currentTime=+$('scrub').value:seekEdited(+$('scrub').value));action('edited-view',()=>selectClip(selected));action('source-view',()=>seekSource(clip()?.start||0));
document.querySelectorAll('[data-tab]').forEach(button=>button.addEventListener('click',()=>{document.querySelectorAll('[data-tab]').forEach(b=>b.classList.toggle('active',b===button));document.querySelectorAll('.tab-content').forEach(p=>p.classList.toggle('hidden',p.id!=='tab-'+button.dataset.tab));}));
action('new-project',async()=>{const name=prompt('프로젝트 이름','오늘의 신상 리뷰');if(!name?.trim())return;const p=await api('/projects',{method:'POST',body:JSON.stringify({name:name.trim()})});await loadProjects(p.id);});bind('projects','change',()=>loadProject($('projects').value));action('rename',()=>mutate(()=>{}));
bind('assets','click',async e=>{const discard=e.target.closest('[data-discard]');if(discard){await api('/uploads/'+discard.dataset.discard,{method:'DELETE'});project=await api('/projects/'+project.id);draw();return;}const node=e.target.closest('[data-asset]');if(node){activeAsset=node.dataset.asset;const i=project.state.clips.findIndex(c=>c.asset_id===activeAsset);if(i>=0)selectClip(i);drawAnalysis();waveform();}});
bind('analysis-asset','change',()=>{activeAsset=$('analysis-asset').value;drawAnalysis();waveform();});
async function analyze(transcribe){requireProject();if(!activeAsset)throw Error('분석할 원본을 선택해 주세요.');const vocabulary=$('vocabulary').value,reference=$('reference-script').value;await mutate(s=>{s.vocabulary=vocabulary;s.reference_script=reference;});const result=await api('/projects/'+project.id+'/analyze',{method:'POST',body:JSON.stringify({asset_id:activeAsset,transcribe,vocabulary,names:vocabulary.split(/[,，\n]/).map(x=>x.trim()).filter(Boolean)})});toast('분석 작업을 시작했어요. 컷 설정에서 결과를 확인해 주세요.');await poll();}
action('analyze',()=>analyze(true));action('vad',()=>analyze(false));
bind('preset','change',()=>{const p={default:[.6,.12,.2],conservative:[.9,.18,.3],fast:[.4,.1,.15]}[$('preset').value];[$('min-gap').value,$('pre-roll').value,$('post-roll').value]=p;drawAnalysis();});['min-gap','pre-roll','post-roll'].forEach(id=>bind(id,'change',drawAnalysis));
bind('candidates','click',async e=>{const b=e.target.closest('[data-context]');if(b){const c=candidates()[+b.dataset.context];seekSource(Math.max(0,c.start-1),Math.min(asset().metadata.duration,c.end+1));}const restore=e.target.closest('[data-restore-gap]');if(restore){const candidate=candidates()[+restore.dataset.restoreGap];await saveQueue;const old=clone(project.state);project=await api('/projects/'+project.id+'/cuts',{method:'POST',body:JSON.stringify({revision:project.revision,asset_id:activeAsset,candidates:[candidate],restore:true})});remember(old);currentSource=null;draw();toast('해당 공백 구간을 복원했어요. 타임라인 순서를 확인해 주세요.');}});
action('apply-candidates',async()=>{const chosen=[...document.querySelectorAll('[data-gap]:checked')].map(e=>candidates()[+e.dataset.gap]);if(!chosen.length)throw Error('적용할 공백 후보를 선택해 주세요.');await saveQueue;const old=clone(project.state);project=await api('/projects/'+project.id+'/cuts',{method:'POST',body:JSON.stringify({revision:project.revision,asset_id:activeAsset,candidates:chosen})});remember(old);rendered=null;currentSource=null;draw();toast('선택한 공백을 제외했어요. 보존 구간은 그대로예요.');});
action('protect',()=>{const p={id:uuid(),asset_id:activeAsset,start:+$('protect-start').value,end:+$('protect-end').value};return mutate(s=>s.protections.push(p));});bind('protections','click',e=>{const b=e.target.closest('[data-unprotect]');if(b)return mutate(s=>s.protections.splice(+b.dataset.unprotect,1));});
bind('transcript','click',e=>{const b=e.target.closest('[data-word]');if(b)seekSource(+b.dataset.word);});action('product-refresh',()=>drawAnalysis());
bind('products','click',e=>{let b=e.target.closest('[data-product]');if(b){const p=asset().analysis.products[+b.dataset.product];seekSource(p.start,p.end);return;}b=e.target.closest('[data-product-add]');if(b){const p=asset().analysis.products[+b.dataset.productAdd],name=prompt('제품명을 확인해 주세요',p.name);if(name!==null)return mutate(s=>s.clips.push({id:uuid(),asset_id:activeAsset,start:p.start,end:p.end,label:name,frame:{mode:'fit',x:.5,y:.5,zoom:1}}));}});
bind('timeline-track','click',e=>{const b=e.target.closest('[data-clip]');if(b)selectClip(+b.dataset.clip);});
action('add-clip',()=>{const a=asset();if(!a||a.status!=='ready')throw Error('검사 완료 원본을 선택해 주세요.');return mutate(s=>s.clips.push({id:uuid(),asset_id:a.id,start:0,end:a.metadata.duration,label:a.name.replace(/\.[^.]+$/,''),frame:{mode:'fit',x:.5,y:.5,zoom:1}}));});
action('clip-save',()=>{const i=selected,label=$('clip-label').value,start=+$('clip-start').value,end=+$('clip-end').value;return mutate(s=>Object.assign(s.clips[i],{label,start,end}));});action('clip-delete',()=>{const i=selected;return mutate(s=>s.clips.splice(i,1));});
action('clip-duplicate',()=>{const i=selected;return mutate(s=>s.clips.splice(i+1,0,{...clone(s.clips[i]),id:uuid()}));});
action('clip-split',()=>{const c=clip();if(!c)throw Error('유지 구간을 선택해 주세요.');const value=prompt('원본 기준 분리할 시간(초)',seconds(mode==='edited'&&$('player').currentTime>c.start&&$('player').currentTime<c.end?$('player').currentTime:(c.start+c.end)/2));if(value===null)return;const time=+value;if(!(time>c.start&&time<c.end))throw Error('구간 안의 시간을 입력해 주세요.');const i=selected;return mutate(s=>{const old=s.clips[i];s.clips.splice(i,1,{...old,end:time},{...clone(old),id:uuid(),start:time});});});
action('clip-merge',()=>{const i=selected;return mutate(s=>{const a=s.clips[i],b=s.clips[i+1];if(!b||a.asset_id!==b.asset_id||Math.abs(a.end-b.start)>.001)throw Error('같은 원본의 연속된 구간만 합칠 수 있어요.');a.end=b.end;s.clips.splice(i+1,1);});});
for(const [id,delta]of [['clip-left',-1],['clip-right',1]])action(id,()=>{const i=selected,n=i+delta;if(n<0||n>=project.state.clips.length)return;selected=n;return mutate(s=>[s.clips[i],s.clips[n]]=[s.clips[n],s.clips[i]]);});
action('undo',async()=>{if(!history.length)return;const state=history.pop();future.push(clone(project.state));await mutate(s=>Object.assign(s,state),false);});action('redo',async()=>{if(!future.length)return;const state=future.pop();history.push(clone(project.state));await mutate(s=>Object.assign(s,state),false);});
function frameValues(){return{mode:$('frame-mode').value,x:+$('frame-x').value,y:+$('frame-y').value,zoom:+$('frame-zoom').value};}
action('frame-save',()=>{const i=selected,frame=frameValues();return mutate(s=>{if(!s.clips[i])throw Error('유지 구간을 선택해 주세요.');s.clips[i].frame=frame;});});action('frame-all',()=>{const frame=frameValues();return mutate(s=>s.clips.forEach(c=>c.frame=clone(frame)));});bind('frame-zoom','input',()=>$('zoom-value').textContent=$('frame-zoom').value+'×');bind('show-guides','change',()=>$('guides').classList.toggle('hidden',!$('show-guides').checked));
action('generate-captions',async()=>{requireProject();await saveQueue;const old=clone(project.state);project=await api('/projects/'+project.id+'/captions',{method:'POST',body:JSON.stringify({revision:project.revision,target:+$('caption-target').value})});remember(old);draw();if(!project.state.captions.items.length)toast('인식된 대사가 없어요. 음성 인식을 실행하거나 자막을 직접 추가해 주세요.');});
action('add-caption',()=>{if(!editedLength())throw Error('먼저 유지 구간을 추가해 주세요.');return mutate(s=>{if(s.captions.items.length&&!captionSynced())throw Error('기존 자막을 먼저 동기화해 주세요.');const last=s.captions.items.at(-1),start=last?.end||0,end=Math.min(editedLength(s),start+2);if(end<=start)throw Error('추가할 자막 시간 여유가 없어요.');s.captions.signature=project.signature;s.captions.items.push({id:uuid(),start,end,text:'자막을 입력해 주세요',edited:true,review:true});});});
bind('caption-list','change',e=>{const node=e.target;const key=node.dataset.captionText!==undefined?'text':node.dataset.captionStart!==undefined?'start':node.dataset.captionEnd!==undefined?'end':null;if(!key)return;const i=+(node.dataset.captionText??node.dataset.captionStart??node.dataset.captionEnd),value=key==='text'?node.value:+node.value;return mutate(s=>{captionFindings.delete(s.captions.items[i].id);Object.assign(s.captions.items[i],{[key]:value,edited:true,review:true,review_token:''});});});
action('save-corrections',()=>{const value=$('corrections').value;return mutate(s=>{s.corrections=value;captionFindings.clear();});});
bind('caption-list','click',async e=>{const b=e.target.closest('button');if(!b)return;let index;
if(b.dataset.captionSource!==undefined){const c=project.state.captions.items[+b.dataset.captionSource];activeAsset=c.source_asset_id;seekSource(Math.max(0,c.source_start-.6),Math.min(asset().metadata.duration,c.source_end+.6));return;}
if(b.dataset.captionInspect!==undefined){await saveQueue;const c=project.state.captions.items[+b.dataset.captionInspect];captionFindings.set(c.id,await api('/proofread',{method:'POST',body:JSON.stringify({text:c.text,corrections:project.state.corrections||''})}));drawCaptions();return;}
if(b.dataset.captionSuggestion!==undefined){index=+b.closest('.caption-card').querySelector('[data-caption-text]').dataset.captionText;const c=project.state.captions.items[index],suggestion=captionFindings.get(c.id).suggestions[+b.dataset.captionSuggestion];return mutate(s=>{const value=s.captions.items[index];value.text=applySuggestion(value.text,suggestion);value.edited=true;value.review_token='';captionFindings.delete(value.id);});}
if(b.dataset.captionApprove!==undefined){await saveQueue;const old=clone(project.state),c=project.state.captions.items[+b.dataset.captionApprove];project=await api('/projects/'+project.id+'/captions/review',{method:'POST',body:JSON.stringify({revision:project.revision,caption_ids:[c.id]})});remember(old);draw();return;}
if(b.dataset.captionPlay!==undefined){seekEdited(Math.max(0,project.state.captions.items[+b.dataset.captionPlay].start-.6),true);return;}if(b.dataset.captionDelete!==undefined)return mutate(s=>s.captions.items.splice(+b.dataset.captionDelete,1));if(b.dataset.captionSplit!==undefined){index=+b.dataset.captionSplit;const text=project.state.captions.items[index].text;const value=prompt('두 자막 사이에 | 를 넣어 나눠 주세요',text);if(value===null)return;const parts=value.split('|');if(parts.length!==2||parts.some(p=>!p.trim()))throw Error('나눌 두 문구 사이에 | 하나를 넣어주세요.');return mutate(s=>{const c=s.captions.items[index],middle=(c.start+c.end)/2;s.captions.items.splice(index,1,{...c,end:middle,text:parts[0].trim(),edited:true,review:true},{...c,id:uuid(),start:middle,text:parts[1].trim(),edited:true,review:true});});}if(b.dataset.captionMerge!==undefined){index=+b.dataset.captionMerge;return mutate(s=>{const a=s.captions.items[index],next=s.captions.items[index+1];if(!next)throw Error('다음 자막이 없어요.');a.end=next.end;a.text+=' '+next.text;a.edited=true;a.review=true;s.captions.items.splice(index+1,1);});}});
bind('srt-download','click',async e=>{e.preventDefault();requireProject();await saveQueue;if(!captionSynced()||project.state.captions.items.some(c=>c.text.trim()&&!c.reviewed))throw Error('자막 동기화와 원음 검수를 완료해 주세요.');await downloadSavedFile(`/api/projects/${project.id}/captions.srt`,'iyoring_review_roughcut.srt');});
async function startRender(preview,forceFull=false){requireProject();if(!project.state.clips.length)throw Error('내보낼 유지 구간이 없어요.');const fps=+$('fps').value,quality=$('quality').value;if(project.state.fps!==fps||project.state.quality!==quality)await mutate(s=>{s.fps=fps;s.quality=quality;});await api('/projects/'+project.id+'/render',{method:'POST',body:JSON.stringify({revision:project.revision,mode:preview||forceFull?'full':$('export-mode').value,preview,filename:$('filename').value})});toast(preview?'렌더 미리보기를 만들고 있어요.':'원본으로 출력 작업을 시작했어요.');await poll();}
action('render-preview',()=>startRender(true));action('export',()=>startRender(false));
function drawQuick(){
  const ready=asset()?.status==='ready', busy=quickStarting||latestAuto&&['queued','running'].includes(latestAuto.status);
  $('auto-cut').disabled=!ready||Boolean(busy);$('auto-cut').textContent=busy?'무음 자동 편집 중…':'무음 자동 편집 시작';
  document.querySelector('.quick-edit').classList.toggle('busy',Boolean(busy));
  $('quick-progress').classList.toggle('hidden',!busy);$('quick-progress').firstElementChild.style.width=Math.round((latestAuto?.progress||0)*100)+'%';
  const applied=latestAuto?.result.applied, current=applied&&latestAuto.result.render_signature===project?.render_signature;
  $('quick-play').classList.toggle('hidden',!current);$('quick-export').classList.toggle('hidden',!current);$('auto-undo').classList.toggle('hidden',!applied||project?.revision!==latestAuto.result.revision);
  if(busy)$('quick-status').textContent=latestAuto?.message||'자동 편집을 시작하고 있어요. 창을 열어두고 기다려 주세요.';
  else if(latestAuto&&['failed','cancelled'].includes(latestAuto.status))$('quick-status').textContent=(applied?'컷은 적용된 상태입니다. ':'')+latestAuto.message;
  else if(current){const r=latestAuto.result;$('quick-status').textContent=`자동 편집 완료 · ${clock(r.before_seconds)} → ${clock(r.after_seconds)} · ${seconds(r.removed_seconds)}초 삭제`+(r.removed_seconds<1/project.state.fps?' · 삭제할 무음이 없거나 보존 구간으로 지정되어 원본 길이를 유지했어요.':'')+(r.notice?'\n'+r.notice:'');}
  else $('quick-status').textContent=ready?(applied?'편집 내용이 변경됐어요. 현재 편집본을 재생하거나 자동 편집을 다시 실행할 수 있어요.':'준비됐어요. 선택한 원본에서 무음을 찾아 바로 컷편집해요.'):'먼저 왼쪽에서 촬영 원본을 올려주세요. 프로젝트는 자동으로 만들어져요.';
  const downloadable=latestExport?.status==='completed'&&latestExport.result.render_signature===project?.render_signature;
  $('quick-downloads').innerHTML=downloadable?(latestExport.result.files||[]).filter(f=>['video','archive'].includes(f.type)).map(f=>`<a class="button primary" href="/api/exports/${latestExport.id}/${encodeURIComponent(f.name)}">${f.type==='video'?'편집본 MP4 다운로드':'편집본 ZIP 다운로드'} · ${bytes(f.size)}</a>`).join(''):'';
}
async function startAutoCut(){
  requireProject();await saveQueue;if(!asset()||asset().status!=='ready')throw Error('검사가 완료된 원본을 선택해 주세요.');
  quickStarting=true;drawQuick();
  try{await api('/projects/'+project.id+'/auto-cut',{method:'POST',body:JSON.stringify({revision:project.revision,asset_id:activeAsset,threshold_db:+$('silence-level').value,minimum:+$('min-gap').value,before:+$('pre-roll').value,after:+$('post-roll').value})});await poll();}
  finally{quickStarting=false;drawQuick();}
}
action('auto-cut',startAutoCut);
action('quick-play',()=>{const r=latestAuto?.result,video=r?.files?.find(f=>f.type==='video');if(video&&r.render_signature===project.render_signature){rendered=latestAuto.id;mode='edited';$('edited-view').classList.add('active');$('source-view').classList.remove('active');setSource('/api/exports/'+rendered+'/'+encodeURIComponent(video.name)+'?inline=true',0,true);$('preview-label').textContent='무음 자동 편집본 · 미리보기 화질';}else seekEdited(0,true);});
action('quick-export',()=>startRender(false,true));
action('auto-undo',async()=>{await saveQueue;const old=clone(project.state);project=await api('/projects/'+project.id+'/auto-cut/'+latestAuto.id+'/undo',{method:'POST',body:JSON.stringify({revision:project.revision})});remember(old);rendered=null;currentSource=null;draw();toast('자동 편집 전 타임라인으로 되돌렸어요.');});
async function poll(){if(!project||$('login-dialog').open)return;const id=project.id,jobs=await api('/jobs?project_id='+id);if(project.id!==id)return;const status={'queued':'대기 중','running':'처리 중','completed':'완료','failed':'실패','cancelled':'취소됨'};let refresh=false, completedAuto=null;
  latestScript=jobs.find(j=>j.kind==='script_edit')||null;latestAuto=jobs.find(j=>j.kind==='auto_cut')||null;latestExport=jobs.find(j=>j.kind==='render'&&!j.result.preview)||null;
  if(requestedScriptPreview){const j=jobs.find(j=>j.id===requestedScriptPreview);if(j&&['completed','failed','cancelled'].includes(j.status)){requestedScriptPreview=null;const f=j.result.files?.find(f=>f.type==='video');if(j.status==='completed'&&f&&j.result.render_signature===project.render_signature){rendered=j.id;mode='edited';setSource(`/api/exports/${j.id}/${encodeURIComponent(f.name)}?inline=true`,0,true);$('preview-label').textContent='선택한 실제 영상·원음 연결 · 미리보기';}else toast(j.message||'미리보기 생성에 실패했습니다.');}}
  if(finalDownloading){const j=jobs.find(j=>j.id===finalDownloading);if(j&&['completed','failed','cancelled'].includes(j.status)){finalDownloading=null;if(j.status==='completed'&&j.result.render_signature===project.render_signature)await saveFinalVideo(j);else toast(j.status==='completed'?'편집이 변경되어 이전 출력은 자동 다운로드하지 않습니다.':'최종 편집본 생성 실패: '+j.message,true);}}
  for(const j of jobs){if(currentJobIds.get(j.id)!==j.status&&['completed','failed','cancelled'].includes(j.status)&&['analyze','ingest','auto_cut','script_edit'].includes(j.kind)){refresh=true;if(['auto_cut','script_edit'].includes(j.kind)&&j.result.applied&&currentJobIds.has(j.id))completedAuto=j;}if(!saving||!['completed','failed','cancelled'].includes(j.status))currentJobIds.set(j.id,j.status);}
  $('jobs').innerHTML=jobs.map(j=>`<div class="job"><b>${{ingest:'원본 검사',analyze:'대사·음성 분석',auto_cut:'무음 자동 편집',script_edit:'대본 자동 편집',render:j.result.preview?'렌더 미리보기':'영상 내보내기'}[j.kind]} · ${status[j.status]}</b>${j.result.revision?`<small>편집 버전 ${j.result.revision} ${j.result.revision!==project.revision?'· 현재 편집과 버전이 다릅니다':''}</small>`:''}<div class="progress"><i style="width:${Math.round(j.progress*100)}%"></i></div><small>${esc(j.result.notice||j.message)}</small><div class="button-row">${['queued','running'].includes(j.status)?`<button class="danger" data-cancel-job="${j.id}">취소</button>`:''}${['failed','cancelled'].includes(j.status)?`<button class="secondary" data-retry-job="${j.id}">다시 실행</button>`:''}${(j.result.files||[]).map(f=>f.type==='video'&&j.result.preview?`<button class="secondary" data-preview-job="${j.id}" data-file="${esc(f.name)}" data-signature="${esc(j.result.render_signature)}">편집본 재생</button>`:`<a class="button secondary" href="/api/exports/${j.id}/${encodeURIComponent(f.name)}">${esc(f.name)} · ${bytes(f.size)}</a>`).join('')}${['completed','failed','cancelled'].includes(j.status)&&j.kind==='render'?`<button class="ghost" data-clean-job="${j.id}">출력 정리</button>`:''}</div></div>`).join('')||'<p class="muted">자동 편집 진행과 다운로드가 여기에 표시돼요.</p>';
  if(refresh&&!saving){const current=await api('/projects/'+id);if(project.id!==id)return;if(completedAuto&&current.revision===completedAuto.result.revision)remember(project.state);project=current;if(completedAuto){selected=0;rendered=null;currentSource=null;}draw();if(completedAuto?.status==='completed'&&completedAuto.result.render_signature===project.render_signature){$(completedAuto.kind==='script_edit'?'script-play':'quick-play').click();toast(completedAuto.kind==='script_edit'?'대본 순서로 구간을 연결했어요. 찾지 못한 대사와 실제 장면을 확인해 주세요.':'무음 컷을 적용했어요. 편집본을 확인하고 고화질 MP4를 저장해 주세요.');}}
  drawQuick();drawScript();
}
bind('jobs','click',async e=>{const b=e.target.closest('button');if(!b)return;if(b.dataset.cancelJob)await api('/jobs/'+b.dataset.cancelJob+'/cancel',{method:'POST'});if(b.dataset.retryJob)await api('/jobs/'+b.dataset.retryJob+'/retry',{method:'POST'});if(b.dataset.cleanJob)await api('/exports/'+b.dataset.cleanJob,{method:'DELETE'});if(b.dataset.previewJob){if(b.dataset.signature!==project.render_signature)throw Error('이 미리보기는 이전 컷 버전이에요. 최신 렌더 미리보기를 만들어 주세요.');rendered=b.dataset.previewJob;mode='edited';setSource('/api/exports/'+rendered+'/'+encodeURIComponent(b.dataset.file)+'?inline=true',0,true);$('preview-label').textContent='렌더 미리보기 · 최종 출력과 같은 컷·화면·색 변환';applyFrame();}await poll();});

async function uploadFiles(files){
  if(!globalThis.crypto?.subtle)throw Error('안전한 HTTPS 연결이 필요합니다. 지원되는 최신 브라우저로 접속해 주세요.');
  if(uploadAbort)throw Error('현재 업로드가 끝난 뒤 추가해 주세요.');
  if(!project){const draft={script:$('edit-script').value,directions:$('edit-directions').value};const p=await api('/projects',{method:'POST',body:JSON.stringify({name:'오늘의 신상 리뷰'})});await loadProjects(p.id);$('edit-script').value=draft.script;$('edit-directions').value=draft.directions;}
  uploadPaused=false;uploadAbort=new AbortController();drawScript();$('upload-progress').classList.remove('hidden');
  try{for(const file of files){
    if(file.size>config.max_file_bytes)throw Error(`${file.name}: 파일당 최대 10GB(10,000,000,000바이트)입니다. 원본을 나눠 주세요.`);
    if(!file.size)throw Error('빈 파일은 올릴 수 없어요.');
    const key=`studio-upload-${project.id}-${file.name}-${file.size}-${file.lastModified}`;let saved=localStorage.getItem(key),session;
    if(saved){try{session=await api('/uploads/'+saved);}catch{localStorage.removeItem(key);}}
    if(session&&session.status!=='uploading'){toast(file.name+'은 이미 업로드됐어요.');continue;}
    if(!session){session=await api('/projects/'+project.id+'/uploads',{method:'POST',body:JSON.stringify({name:file.name,size:file.size})});localStorage.setItem(key,session.id);}
    const known=new Map((Array.isArray(session.chunks)?session.chunks:[]).map(c=>[c.idx,c.digest]));const size=config.chunk_bytes,total=Math.ceil(file.size/size);
    for(let index=0;index<total;index++){
      if(uploadPaused)throw Error('업로드를 중단했어요. 같은 파일을 다시 선택하면 검증 후 이어올릴 수 있어요.');
      const chunk=file.slice(index*size,Math.min(file.size,(index+1)*size));
      $('upload-progress').innerHTML=`<small>${esc(file.name)} · ${Math.floor(index/total*100)}% ${known.has(index)?'기존 청크 확인':'업로드 중'}</small><div class="progress"><i style="width:${index/total*100}%"></i></div><button id="pause-upload" class="ghost">중단 · 나중에 이어올리기</button>`;
      $('pause-upload').onclick=()=>{uploadPaused=true;uploadAbort?.abort();};
      // Hash only one 8MiB chunk, including previously uploaded chunks. Never read the whole file.
      const chunkBuffer=await chunk.arrayBuffer();const hash=[...new Uint8Array(await crypto.subtle.digest('SHA-256',chunkBuffer))].map(n=>n.toString(16).padStart(2,'0')).join('');
      if(known.has(index)){if(known.get(index)!==hash)throw Error('같은 이름의 다른 원본입니다. 기존 업로드를 정리한 뒤 새로 시작해 주세요.');continue;}
      let done=false;
      for(let attempt=0;attempt<4&&!done;attempt++){
        try{const response=await fetch(`/api/uploads/${session.id}/chunks/${index}`,{method:'PUT',body:chunk,signal:uploadAbort.signal,headers:{'Content-Type':'application/octet-stream'}});const result=await response.json();if(!response.ok){const failure=Error(result.detail||'청크 전송 실패');failure.permanent=response.status<500||response.status===507;throw failure;}if(result.digest!==hash)throw Error('청크 검증에 실패했어요.');done=true;}
        catch(error){if(error.name==='AbortError'||uploadPaused)throw Error('업로드를 중단했어요. 같은 파일을 다시 선택하면 이어올릴 수 있어요.');if(error.permanent||attempt===3)throw error;await new Promise(resolve=>setTimeout(resolve,500*2**attempt));}
      }
    }
    await api('/uploads/'+session.id+'/complete',{method:'POST'});localStorage.removeItem(key);toast(file.name+' 업로드 완료 · 영상 정보를 검사하고 있어요.');
  }}finally{uploadAbort=null;project=await api('/projects/'+project.id);draw();$('upload-progress').classList.add('hidden');await poll();}
}
bind('dubbing-upload','change',async e=>{const files=[...e.target.files];e.target.value='';await uploadFiles(files);});
bind('upload','change',async e=>{const files=[...e.target.files];e.target.value='';await uploadFiles(files);});for(const event of ['dragenter','dragover'])$('dropzone').addEventListener(event,e=>{e.preventDefault();$('dropzone').classList.add('drag');});for(const event of ['dragleave','drop'])$('dropzone').addEventListener(event,e=>{e.preventDefault();$('dropzone').classList.remove('drag');if(event==='drop')uploadFiles([...e.dataTransfer.files]).catch(error=>toast(error.message));});
bind('login-form','submit',async e=>{e.preventDefault();try{await api('/login',{method:'POST',body:JSON.stringify({password:$('password').value})});$('password').value='';$('login-dialog').close();await init();}catch(error){$('login-error').textContent=error.message;}});$('login-dialog').addEventListener('cancel',e=>e.preventDefault());action('logout',async()=>{await api('/logout',{method:'POST'});$('player').pause();location.reload();});
function modelInfo(){
  $('model-status').textContent=config.model_ready?`한국어 Whisper ${config.model_name} 준비됨 · 제품명은 등록하고 원음을 검수해 주세요.`:(config.desktop?'자막 모델을 준비하고 있어요. 상단에서 진행 상황을 확인해 주세요.':'자막 모델 설치 전이에요. 위의 무음 자동 편집은 바로 사용할 수 있어요.');
  $('analyze').disabled=!config.model_ready;drawScript();
}
async function refreshDesktop(){
  if(!config?.desktop || $('login-dialog').open)return;
  const status=await api('/desktop/status');
  $('desktop-setup').classList.remove('hidden');
  $('desktop-setup').dataset.status=status.status;
  $('desktop-setup-message').textContent=status.message;
  $('desktop-setup-detail').textContent=status.status==='preparing'&&status.downloaded_bytes?`받은 파일 ${bytes(status.downloaded_bytes)} · 처음 한 번 준비하면 다음부터 재사용해요.`:'';
  $('desktop-setup-retry').classList.toggle('hidden',!status.can_retry);
  config.model_ready=status.status==='ready';modelInfo();
}
action('desktop-setup-retry',async()=>{await api('/desktop/retry',{method:'POST'});await refreshDesktop();});
async function init(){try{config=await api('/config');$('storage').textContent=bytes(config.free_bytes);modelInfo();clearInterval(desktopTimer);if(config.desktop){await refreshDesktop();desktopTimer=setInterval(()=>refreshDesktop().catch(()=>{}),2000);}await loadProjects();clearInterval(pollTimer);pollTimer=setInterval(()=>poll().catch(e=>console.warn(e.message)),2000);}catch(error){if(!$('login-dialog').open)toast(error.message);}}
window.addEventListener('resize',waveform);window.addEventListener('DOMContentLoaded',init);

const exampleScript=`아니 제가 CU 다섯 곳이나 돌아서 겨우 3개 구했거든요?
과연 찾아다닐 만큼 맛있을까?
빠르게 먹어볼게요!
[첫 번째 제품명·실제 맛 평가]이고,
[두 번째 제품명·실제 맛 평가]인데,
[세 번째 제품명·실제 맛 평가].
[찾아다닐 만큼 맛있는지 실제 결론과 이유].
나머지는 매일 재고 검색하고 발품까지 팔았는데 아직 못 찾았어요.
여러분은 다른 빵 먹어보셨어요?`;
function drawScript(){
 if(!config)return;
 if(scriptFormProject!==project?.id){$('edit-script').value=project?.state.script_brief?.script||exampleScript;$('edit-directions').value=project?.state.script_brief?.directions||'9:16, 빠른 템포, 첫 문장 클로즈업, 나머지는 전체 화면. 원음 유지.';scriptFormProject=project?.id;}
 const assets=project?.assets||[],ready=assets.some(a=>a.status==='ready'&&a.metadata.has_video!==false),pending=Boolean(uploadAbort)||assets.some(a=>['uploading','checking'].includes(a.status));
 const busy=scriptStarting||[latestScript,latestAuto].some(j=>j&&['running','queued'].includes(j.status));
 const speech=assets.filter(a=>a.status==='ready'&&a.metadata.has_audio),canRecognize=config.model_ready||speech.length>0&&speech.every(a=>a.analysis.transcribed);
 $('script-start').disabled=!ready||pending||Boolean(busy);$('script-start').textContent=busy?'장면 검색·자동 편집 중…':'대본대로 자동 편집 시작';
 const r=latestScript?.result,current=r?.applied&&r.render_signature===project?.render_signature;
 $('script-play').classList.toggle('hidden',!current);$('script-export').classList.toggle('hidden',!current);$('script-export').disabled=!r?.complete;$('script-undo').classList.toggle('hidden',!r?.applied||project?.revision!==r.revision);
 $('script-progress').classList.toggle('hidden',!busy);$('script-progress').firstElementChild.style.width=Math.round((latestScript?.progress||0)*100)+'%';
 if(busy)$('script-status').textContent=latestScript?.message||'대본 자동 편집을 시작합니다.';
 else if(latestScript&&['failed','cancelled'].includes(latestScript.status))$('script-status').textContent=latestScript.message;
 else if(r?.lines)$('script-status').textContent=`${r.complete?'대본 편집 완료':'부분 미리보기 · 확인 필요'} · ${r.matched}/${r.total}줄 연결`+(r.after_seconds?` · ${clock(r.after_seconds,true)}`:'')+(r.notice?'\n'+r.notice:'')+(!r.complete?'\n장면 후보를 재생하고 선택하세요. 실제 영상에 없는 장면은 정확한 일치 없음으로 표시합니다.':'');
 else $('script-status').textContent=ready?(config.model_ready?'대본과 연출을 입력하고 시작하세요. 더빙 대사를 우선 연결하고, 나머지는 촬영 원음에서 찾습니다.':'장면·OCR 검색은 실행할 수 있어요. 음성 모델 준비 중에는 아직 인식하지 않은 대사 검색을 생략합니다.'):'왼쪽에서 촬영 원본을 올려주세요. 프로젝트는 자동으로 만들어져요.';
 const sceneCard=(c,line,aux)=>`<article class="scene-candidate"><img loading="lazy" src="${esc(c.thumbnail)}" alt="${esc(c.description)}"><div><b>${esc(c.match_type)} · ${esc(c.filename)}</b><p>${clock(c.start)}–${clock(c.end)}</p><p>${esc(c.selection_reason.join(' · '))}</p>${c.ocr.length?`<small>관측 OCR: ${esc(c.ocr.map(o=>o.text).join(' / '))}</small>`:''}<p class="review-note">${esc(c.uncertainties.join(' · '))}</p><div class="button-row"><button class="secondary" data-scene-preview="${c.asset_id}" data-scene-start="${c.start}" data-scene-end="${c.end}">원본 구간 재생</button><button class="secondary" data-scene-select="${esc(c.id)}" data-scene-line="${line}" data-scene-aux="${aux}">${aux?'확인 후 보조 장면으로 사용':'원본 확인 후 이 장면 선택'}</button></div></div></article>`;
 const reportKey=[latestScript?.id,latestScript?.updated,project?.revision].join(':');
 if($('script-report').dataset.renderKey!==reportKey){$('script-report').dataset.renderKey=reportKey;
 $('script-report').innerHTML=r?.lines?`<details ${r.complete?'':'open'}><summary>대본·실제 영상 연결 결과</summary>${r.lines.map(line=>`<div class="script-row ${line.status}"><b>${line.line}. ${esc({matched:'대사 일치',selected:'사용자 선택',needs_scene:'더빙 화면 선택 필요',missing:line.exact?.length?'대사 없음 · 장면 후보 있음':'정확한 일치 없음',placeholder:'내용 미정'}[line.status])}</b><p>${esc(line.script)}</p>${line.source_text?`<p>실제 대사: ${esc(line.source_text)}</p><small>${esc(line.filename||'')} · ${clock(line.start)}–${clock(line.end)} · 대사 유사도 ${Math.round(line.score*100)}%${line.visual_name?' · 더빙 화면: '+esc(line.visual_name):' · 촬영 원음'}</small>`:''}<p>${esc(line.reason||line.visual_reason||'')}</p>${line.intent?`<details><summary>검색 의도·실제 검색 문구</summary><p>대상: ${esc(line.intent.products.map(p=>p.name).join(', ')||'종류·행동 검색')} · 행동: ${esc(line.intent.actions.join(', '))} · 시각 특징: ${esc(line.intent.visual_features.join(', '))} · 의미: ${esc(line.intent.abstract_meaning.join(', '))} · 역할: ${esc(line.intent.roles.join(', '))}</p><p>${esc(line.intent.visual_queries.join(' / '))}</p></details>`:''}${line.status==='placeholder'?'':`<p>${esc(line.scene_status||'')}</p>${(line.exact||[]).map(c=>sceneCard(c,line.line,false)).join('')}${line.supporting?.length?`<details><summary>보조 후보 · 의미·제품을 확정할 근거 부족</summary>${line.supporting.map(c=>sceneCard(c,line.line,true)).join('')}</details>`:''}`}</div>`).join('')}</details><p class="muted">${r.speech_skipped?'음성 모델 준비 전이라 일부 원음 대사 검색은 생략했습니다. ':''}적용한 연출: ${esc(r.directing.supported.join(' · '))}</p>${r.directing.unapplied.map(t=>`<p class="review-note">${esc(t)}</p>`).join('')}`:'';
 }
 $('scene-product-list').innerHTML=(project?.state.scene_products||[]).map((p,i)=>`<p>${esc(p.name)}${p.variant?' · '+esc(p.variant):''} · 참고 ${p.reference_ids.length}개 <button class="ghost" data-scene-product-delete="${i}">삭제</button></p>`).join('');
 const downloadable=latestExport?.status==='completed'&&latestExport.result.render_signature===project?.render_signature;
 $('final-download').disabled=!project?.state.clips.length||Boolean(busy)||Boolean(finalDownloading)||Boolean(project?.state.script_edit&&!project.state.script_edit.complete)||Boolean(r?.lines&&!r.complete);$('final-download').textContent=finalDownloading?'최종 편집본 생성 중…':'최종 편집본 다운로드';
 $('script-downloads').innerHTML=downloadable?(latestExport.result.files||[]).filter(f=>['video','archive'].includes(f.type)).map(f=>`<a class="button primary" href="/api/exports/${latestExport.id}/${encodeURIComponent(f.name)}">${f.type==='video'?'편집본 MP4 다운로드':'편집본 ZIP 다운로드'} · ${bytes(f.size)}</a>`).join(''):'';
}
action('script-start',async()=>{requireProject();await saveQueue;const brief={script:$('edit-script').value,directions:$('edit-directions').value};scriptStarting=true;drawScript();try{await mutate(s=>s.script_brief=brief);await api('/projects/'+project.id+'/script-edit',{method:'POST',body:JSON.stringify({revision:project.revision,brief,voice_mode:'auto'})});await poll();}finally{scriptStarting=false;drawScript();}});
action('script-play',async()=>{const r=latestScript?.result,video=r?.files?.find(f=>f.type==='video');if(video&&r.render_signature===project.render_signature){rendered=latestScript.id;mode='edited';setSource('/api/exports/'+rendered+'/'+encodeURIComponent(video.name)+'?inline=true',0,true);$('preview-label').textContent='대본 순서 자동 편집본 · 미리보기 화질';}else if(project.state.clips.some(c=>c.visual_asset_id)){await saveQueue;const response=await api('/projects/'+project.id+'/render',{method:'POST',body:JSON.stringify({revision:project.revision,mode:'full',preview:true,filename:'선택_장면_미리보기'})});requestedScriptPreview=response.job_id;toast('선택한 영상과 원음을 합쳐 미리보기를 만들고 있습니다.');await poll();}else seekEdited(0,true);});
action('script-export',()=>startRender(false,true));
action('script-undo',async()=>{await saveQueue;const old=clone(project.state);project=await api('/projects/'+project.id+'/auto-cut/'+latestScript.id+'/undo',{method:'POST',body:JSON.stringify({revision:project.revision})});remember(old);rendered=null;currentSource=null;draw();toast('대본 자동 편집 전 타임라인으로 되돌렸어요.');});

let finalDownloading=null,scenePreviewEnd=null,requestedScriptPreview=null;
async function saveFinalVideo(job){
 const f=job.result.files.find(f=>f.type==='video');if(!f)throw Error('완료된 MP4가 없습니다.');
 const a=document.createElement('a');a.href=`/api/exports/${job.id}/${encodeURIComponent(f.name)}`;a.download=f.name;document.body.append(a);a.click();a.remove();
}
action('final-download',async()=>{requireProject();await saveQueue;if(latestExport?.status==='completed'&&latestExport.result.render_signature===project.render_signature){await saveFinalVideo(latestExport);return;}
 const response=await api('/projects/'+project.id+'/render',{method:'POST',body:JSON.stringify({revision:project.revision,mode:'full',preview:false,filename:'최종_편집본'})});finalDownloading=response.job_id;drawScript();await poll();toast('최종 MP4를 만들고 있습니다. 완료되면 다운로드를 시작합니다.');});
bind('script-report','click',async e=>{const b=e.target.closest('button');if(!b)return;
 if(b.dataset.scenePreview){scenePreviewEnd=+b.dataset.sceneEnd;mode='source';setSource('/api/assets/'+b.dataset.scenePreview+'/video',+b.dataset.sceneStart,true);$('preview-label').textContent='검색 후보 원본 · '+clock(+b.dataset.sceneStart)+'–'+clock(scenePreviewEnd);}
 if(b.dataset.sceneSelect){await saveQueue;const previous=clone(project.state);project=await api(`/projects/${project.id}/script-edit/${latestScript.id}/scene`,{method:'POST',body:JSON.stringify({revision:project.revision,line:+b.dataset.sceneLine,candidate_id:b.dataset.sceneSelect,illustration:b.dataset.sceneAux==='true'})});remember(previous);rendered=null;currentSource=null;scenePreviewEnd=null;selected=0;draw();await poll();toast('확인한 실제 장면을 대본 순서에 연결했습니다.');}
});
bind('player','timeupdate',()=>{if(scenePreviewEnd!==null&&$('player').currentTime>=scenePreviewEnd){$('player').pause();scenePreviewEnd=null;}});
action('scene-product-add',async()=>{requireProject();const name=$('scene-product-name').value.trim();if(!name)throw Error('제품명을 입력하세요.');const refs=[];const file=$('scene-product-image').files[0];if(file){const ref=await api('/projects/'+project.id+'/product-references',{method:'POST',body:file,headers:{'Content-Type':file.type}});refs.push(ref.id);}
 const product={name,brand:$('scene-product-brand').value.trim(),kind:$('scene-product-kind').value.trim(),variant:$('scene-product-variant').value.trim(),aliases:$('scene-product-aliases').value.split(',').map(s=>s.trim()).filter(Boolean),features:$('scene-product-features').value.trim(),reference_ids:refs};await mutate(s=>{s.scene_products=s.scene_products||[];s.scene_products.push(product);});for(const id of ['name','brand','kind','variant','aliases','features','image'])$('scene-product-'+id).value='';toast('제품 정보를 저장했습니다. 다시 검색하면 OCR·참고 이미지와 함께 대조합니다.');});
bind('scene-product-list','click',async e=>{const b=e.target.closest('[data-scene-product-delete]');if(b)await mutate(s=>s.scene_products.splice(+b.dataset.sceneProductDelete,1));});
