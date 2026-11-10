/* 단축키: E 자르기, Q 왼쪽(앞) 삭제, W 오른쪽(뒤) 삭제, Del 삭제, Ctrl+C/X/V 복사·잘라내기·붙여넣기, 입력은 자동 저장.
   타임라인 편집: 드래그 순서 변경, 양끝 끌어서 길이 조절, 재생 위치에서 자르기, 단축키. app.js의 전역(project, mutate, selected…)을 사용한다. */
const editMulti=new Set();
(function(){
const FPS=()=>project?.state.fps||30,frame=()=>1/FPS(),snap=t=>Math.round(t*FPS())/FPS();
const track=()=>$('timeline-track');
let dragFrom=null,trimming=null;

// 재생 위치가 가리키는 (구간 번호, 원본 시간). 최종 영상을 재생 중이면 편집본 시간에서 역산한다.
function playhead(){
  if(!project?.state.clips.length)return null;
  const t=$('player').currentTime||0;
  if(rendered){let off=0;for(let i=0;i<project.state.clips.length;i++){const c=project.state.clips[i],len=c.end-c.start;if(t<off+len||i===project.state.clips.length-1)return{index:i,time:c.start+Math.min(len,Math.max(0,t-off))};off+=len;}}
  if(mode==='edited'&&clip())return{index:selected,time:t};
  return null;
}
function needHead(){const h=playhead();if(!h)throw Error('먼저 구간을 선택하고 자를 위치에서 영상을 멈춰 주세요.');const c=project.state.clips[h.index];
  if(!(h.time>c.start+frame()/2&&h.time<c.end-frame()/2))throw Error('재생 위치가 선택한 구간 안에 있어야 해요. 구간을 누르거나 영상을 움직여 주세요.');return {...h,time:snap(h.time)};}

function splitHere(){const h=needHead();return mutate(s=>{const old=s.clips[h.index];s.clips.splice(h.index,1,{...old,end:h.time},{...clone(old),id:uuid(),start:h.time});});}
function trimHead(){const h=needHead();return mutate(s=>{s.clips[h.index].start=h.time;});}
function trimTail(){const h=needHead();return mutate(s=>{s.clips[h.index].end=h.time;});}
function removeSelected(){
  const set=editMulti.size?[...editMulti]:[selected];
  if(!project?.state.clips[set[0]])throw Error('삭제할 구간을 선택해 주세요.');
  const first=Math.min(...set);editMulti.clear();
  return mutate(s=>{s.clips=s.clips.filter((_,i)=>!set.includes(i));selected=Math.max(0,Math.min(first,s.clips.length-1));}).then(()=>{if(project.state.clips.length)selectClip(Math.min(first,project.state.clips.length-1),false);});
}
function duplicate(){const i=selected;if(!project?.state.clips[i])throw Error('복제할 구간을 선택해 주세요.');return mutate(s=>s.clips.splice(i+1,0,{...clone(s.clips[i]),id:uuid()}));}
// 복사·잘라내기·붙여넣기: 선택한 구간(Shift+클릭으로 여러 개)을 복사해 선택한 구간 뒤에 붙인다.
let clipBuffer=[];
function chosen(){const set=editMulti.size?[...editMulti].sort((a,b)=>a-b):[selected];const clips=set.map(i=>project?.state.clips[i]).filter(Boolean);if(!clips.length)throw Error('복사할 구간을 선택해 주세요.');return {set,clips};}
function copyClips(){const {clips}=chosen();clipBuffer=clips.map(c=>clone(c));toast(`구간 ${clipBuffer.length}개를 복사했어요. Ctrl+V로 붙여넣어요.`);}
function cutClips(){copyClips();return removeSelected();}
function pasteClips(){
  if(!clipBuffer.length)throw Error('복사한 구간이 없어요. 구간을 선택하고 Ctrl+C를 눌러 주세요.');
  const missing=clipBuffer.find(c=>!project.assets.some(a=>a.id===c.asset_id||false));
  if(missing)throw Error('복사한 구간의 원본이 이 프로젝트에 없어요.');
  const at=project.state.clips.length?selected+1:0,n=clipBuffer.length;
  return mutate(s=>s.clips.splice(at,0,...clipBuffer.map(c=>({...clone(c),id:uuid()})))).then(()=>{editMulti.clear();selectClip(Math.min(at+n-1,project.state.clips.length-1),false);toast(`구간 ${n}개를 붙여넣었어요.`);});
}
bind('ed-copy','click',copyClips);bind('ed-paste','click',pasteClips);
bind('ed-split','click',splitHere);bind('ed-trim-head','click',trimHead);bind('ed-trim-tail','click',trimTail);bind('ed-delete','click',removeSelected);bind('ed-dup','click',duplicate);

// 클릭: 선택 + 클릭한 위치로 이동(Shift: 여러 개 선택)
track().addEventListener('click',e=>{
  if(e.target.closest('.trim'))return;
  const b=e.target.closest('[data-clip]');if(!b)return;e.stopImmediatePropagation();const i=+b.dataset.clip;
  if(e.shiftKey){if(editMulti.has(i))editMulti.delete(i);else editMulti.add(i);if(!editMulti.has(selected))editMulti.add(selected);draw();return;}
  editMulti.clear();
  const c=project.state.clips[i],r=b.getBoundingClientRect(),f=Math.min(1,Math.max(0,(e.clientX-r.left)/r.width));
  selectClip(i,false);setSource('/api/assets/'+c.asset_id+'/video',snap(c.start+(c.end-c.start)*f),false);
},true);

// 구간 끌어서 순서 변경
track().addEventListener('dragstart',e=>{const b=e.target.closest?.('[data-clip]');if(!b||trimming){e.preventDefault();return;}dragFrom=+b.dataset.clip;b.classList.add('dragging');e.dataTransfer.effectAllowed='move';e.dataTransfer.setData('text/plain',String(dragFrom));});
track().addEventListener('dragover',e=>{if(dragFrom===null)return;const b=e.target.closest('[data-clip]');if(!b)return;e.preventDefault();const r=b.getBoundingClientRect(),after=e.clientX>r.left+r.width/2;track().querySelectorAll('.drop-before,.drop-after').forEach(x=>x.classList.remove('drop-before','drop-after'));b.classList.add(after?'drop-after':'drop-before');});
track().addEventListener('dragend',()=>{dragFrom=null;track().querySelectorAll('.dragging,.drop-before,.drop-after').forEach(x=>x.classList.remove('dragging','drop-before','drop-after'));});
track().addEventListener('drop',e=>{
  if(dragFrom===null)return;const b=e.target.closest('[data-clip]');if(!b)return;e.preventDefault();
  const r=b.getBoundingClientRect(),after=e.clientX>r.left+r.width/2;let to=+b.dataset.clip+(after?1:0),from=dragFrom;dragFrom=null;
  if(from<to)to-=1;if(from===to){draw();return;}
  selected=to;mutate(s=>{const [m]=s.clips.splice(from,1);s.clips.splice(to,0,m);}).catch(error=>toast(error.message));
});

// 양끝 끌어서 길이 조절(원본 시간 기준, 프레임 단위로 맞춤)
track().addEventListener('pointerdown',e=>{
  const h=e.target.closest('.trim');if(!h)return;const b=h.closest('[data-clip]'),i=+b.dataset.clip,c=project.state.clips[i];
  e.preventDefault();e.stopPropagation();b.draggable=false;h.setPointerCapture?.(e.pointerId);
  trimming={i,side:h.dataset.trim,x:e.clientX,width:b.getBoundingClientRect().width,len:c.end-c.start,start:c.start,end:c.end,el:b,dt:0};
});
window.addEventListener('pointermove',e=>{
  if(!trimming)return;const t=trimming,dt=(e.clientX-t.x)/Math.max(20,t.width)*t.len;t.dt=dt;
  const a=project.assets.find(x=>x.id===project.state.clips[t.i].asset_id),max=a?.metadata.duration??Infinity;
  const v=t.side==='l'?Math.min(Math.max(0,t.start+dt),t.end-frame()):Math.max(Math.min(max,t.end+dt),t.start+frame());
  t.value=snap(v);t.el.title=(t.side==='l'?'시작 ':'종료 ')+t.value.toFixed(2)+'초';
  t.el.style.outline='2px solid #c0392b';
});
window.addEventListener('pointerup',()=>{
  if(!trimming)return;const t=trimming;trimming=null;t.el.draggable=true;t.el.style.outline='';
  if(t.value===undefined||Math.abs(t.dt)<1e-6)return;
  const key=t.side==='l'?'start':'end';
  mutate(s=>{s.clips[t.i][key]=t.value;}).then(()=>selectClip(t.i,false)).catch(error=>toast(error.message));
});

// 재생 위치 표시선
function drawPlayhead(){
  const el=$('playhead'),h=playhead();if(!h||!track().children.length){el.classList.add('hidden');return;}
  const b=track().querySelector(`[data-clip="${h.index}"]`);if(!b){el.classList.add('hidden');return;}
  const c=project.state.clips[h.index],f=Math.min(1,Math.max(0,(h.time-c.start)/Math.max(.001,c.end-c.start)));
  const tr=track().getBoundingClientRect(),r=b.getBoundingClientRect();
  el.style.left=(r.left-tr.left+track().scrollLeft+r.width*f)+'px';el.classList.remove('hidden');
}
$('player').addEventListener('timeupdate',drawPlayhead);$('player').addEventListener('seeked',drawPlayhead);
new MutationObserver(drawPlayhead).observe(track(),{childList:true});

// 단축키(입력창에 글자를 쓰는 중에는 동작하지 않음)
document.addEventListener('keydown',e=>{
  const tag=(e.target.tagName||'').toLowerCase();if(['input','textarea','select'].includes(tag)||e.target.isContentEditable||!project)return;
  const key=e.key,ctrl=e.ctrlKey||e.metaKey,run=fn=>{e.preventDefault();try{Promise.resolve(fn()).catch(x=>toast(x.message));}catch(x){toast(x.message);}};
  const p=$('player');
  if(ctrl&&key.toLowerCase()==='z')return run(()=>$(e.shiftKey?'redo':'undo').click());
  if(ctrl&&key.toLowerCase()==='y')return run(()=>$('redo').click());
  if(ctrl&&key.toLowerCase()==='d')return run(duplicate);
  if(ctrl&&key.toLowerCase()==='c')return run(copyClips);
  if(ctrl&&key.toLowerCase()==='x')return run(cutClips);
  if(ctrl&&key.toLowerCase()==='v')return run(pasteClips);
  if(ctrl||e.altKey)return;
  if(key==='e'||key==='E')return run(splitHere);
  if(key==='q'||key==='Q')return run(trimHead);
  if(key==='w'||key==='W')return run(trimTail);
  if(key==='Delete'||key==='Backspace')return run(removeSelected);
  if(key===' ')return run(()=>p.paused?p.play():p.pause());
  if(key==='ArrowLeft'||key==='ArrowRight')return run(()=>{p.pause();p.currentTime=Math.max(0,p.currentTime+(key==='ArrowLeft'?-1:1)*(e.shiftKey?1:frame()));});
  if(key==='['||key===']')return run(()=>{const n=selected+(key==='['?-1:1);if(project.state.clips[n])selectClip(n,false);});
});
})();

/* 자동 저장: 입력을 멈추고 1초 뒤 저장한다(구간 경계·이름·화면 설정·표기 사전·분석용 메모). 저장 버튼을 눌러도 같은 결과. */
(function(){
const groups={
  clip:{ids:['clip-label','clip-start','clip-end'],save(){const i=selected,c=project.state.clips[i];if(!c)return;const label=$('clip-label').value,start=+$('clip-start').value,end=+$('clip-end').value,max=project.assets.find(a=>a.id===c.asset_id)?.metadata.duration??Infinity;
    if(!(Number.isFinite(start)&&Number.isFinite(end)&&start>=0&&end>start&&end<=max+.001))throw Error('구간 시작·종료 시간을 확인해 주세요(자동 저장 보류).');
    if(label===(c.label||'')&&start===c.start&&end===c.end)return;return mutate(s=>Object.assign(s.clips[i],{label,start,end}));}},
  frame:{ids:['frame-mode','frame-x','frame-y','frame-zoom'],save(){const i=selected;if(!project.state.clips[i])return;const f=frameValues();if(JSON.stringify(f)===JSON.stringify(project.state.clips[i].frame))return;return mutate(s=>{s.clips[i].frame=f;});}},
  name:{ids:['project-name'],save(){const name=$('project-name').value.trim();if(!name||name===project.name)return;return mutate(()=>{});}},
  corrections:{ids:['corrections'],save(){const v=$('corrections').value;if(v===(project.state.corrections||''))return;return mutate(s=>{s.corrections=v;captionFindings.clear();});}},
  notes:{ids:['vocabulary','reference-script'],save(){const vocabulary=$('vocabulary').value,reference=$('reference-script').value;if(vocabulary===(project.state.vocabulary||'')&&reference===(project.state.reference_script||''))return;return mutate(s=>{s.vocabulary=vocabulary;s.reference_script=reference;},false);}}
};
const timers={};
function flag(text){const el=$('save-status');if(el)el.textContent=text;}
for(const [name,g] of Object.entries(groups)){
  for(const id of g.ids){
    const el=$(id);if(!el)continue;
    el.addEventListener('input',()=>{if(!project)return;flag('입력 중… 곧 자동 저장돼요');clearTimeout(timers[name]);
      timers[name]=setTimeout(()=>{try{Promise.resolve(g.save()).catch(e=>toast(e.message));}catch(e){toast(e.message);}},1000);});
  }
}
// 대본·연출 지침·유형 입력은 이 브라우저에 임시 저장해 두었다가 다시 열면 복원(편집에 적용된 지침과 구분하려고 서버 상태는 건드리지 않음)
const drafts=['edit-script','edit-directions','guided-text'];
const key=id=>`studio-draft:${project?.id}:${id}`;
for(const id of drafts){const el=$(id);if(!el)continue;
  el.addEventListener('input',()=>{if(!project)return;try{localStorage.setItem(key(id),el.value);}catch{}});}
let restored=null;
setInterval(()=>{if(!project||restored===project.id)return;restored=project.id;
  for(const id of drafts){const el=$(id);if(!el)continue;try{const v=localStorage.getItem(key(id));if(v!==null&&v!==el.value&&!el.matches(':focus'))el.value=v;}catch{}}},700);
})();
