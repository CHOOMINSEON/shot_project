/* 타임라인 편집: 드래그 순서 변경, 양끝 끌어서 길이 조절, 재생 위치에서 자르기, 단축키. app.js의 전역(project, mutate, selected…)을 사용한다. */
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
  if(ctrl||e.altKey)return;
  if(key==='s'||key==='S')return run(splitHere);
  if(key==='q'||key==='Q')return run(trimHead);
  if(key==='w'||key==='W')return run(trimTail);
  if(key==='Delete'||key==='Backspace')return run(removeSelected);
  if(key===' ')return run(()=>p.paused?p.play():p.pause());
  if(key==='ArrowLeft'||key==='ArrowRight')return run(()=>{p.pause();p.currentTime=Math.max(0,p.currentTime+(key==='ArrowLeft'?-1:1)*(e.shiftKey?1:frame()));});
  if(key==='['||key===']')return run(()=>{const n=selected+(key==='['?-1:1);if(project.state.clips[n])selectClip(n,false);});
});
})();
