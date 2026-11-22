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
window.editorOps={splitHere,trimHead,trimTail};   // 편집 채팅에서 사용
bind('ed-copy','click',copyClips);bind('ed-paste','click',pasteClips);
bind('ed-split','click',splitHere);bind('ed-trim-head','click',trimHead);bind('ed-trim-tail','click',trimTail);bind('ed-delete','click',removeSelected);bind('ed-dup','click',duplicate);

// 클릭: 선택 + 클릭한 위치로 이동(Shift: 여러 개 선택)
track().addEventListener('click',e=>{
  if(e.target.closest('.trim'))return;
  if(justDragged){justDragged=false;e.stopImmediatePropagation();e.preventDefault();return;}
  const b=e.target.closest('[data-clip]');if(!b)return;e.stopImmediatePropagation();const i=+b.dataset.clip;
  if(e.shiftKey){if(editMulti.has(i))editMulti.delete(i);else editMulti.add(i);if(!editMulti.has(selected))editMulti.add(selected);draw();return;}
  editMulti.clear();
  const c=project.state.clips[i],r=b.getBoundingClientRect(),f=Math.min(1,Math.max(0,(e.clientX-r.left)/r.width)),at=snap(c.start+(c.end-c.start)*f);
  if(tool==='blade'&&at>c.start+frame()/2&&at<c.end-frame()/2){hideCut();
    mutate(s=>{const old=s.clips[i];s.clips.splice(i,1,{...old,end:at},{...clone(old),id:uuid(),start:at});})
      .then(()=>{selectClip(i+1,false);}).catch(error=>toast(error.message));return;}
  selectClip(i,false);setSource('/api/assets/'+c.asset_id+'/video',at,false);
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

// 마우스 왼쪽을 누른 채 끌면 구간을 자유롭게 옮긴다(자르기·선택 도구 모두). 6px 안쪽으로 움직이면 클릭으로 본다.
let press=null,justDragged=false;
function dropSpot(x,moving){const items=[...track().querySelectorAll('[data-clip]')].filter(el=>el!==moving);
  for(const el of items){const r=el.getBoundingClientRect();if(x<r.left+r.width/2)return {el,after:false};}
  const last=items[items.length-1];return last?{el:last,after:true}:null;}
function clearDrop(){track().querySelectorAll('.drop-before,.drop-after').forEach(x=>x.classList.remove('drop-before','drop-after'));}
track().addEventListener('pointerdown',e=>{
  if(e.button!==0||e.shiftKey||e.target.closest('.trim'))return;const b=e.target.closest('[data-clip]');if(!b)return;
  press={i:+b.dataset.clip,x:e.clientX,el:b,moved:false};
});
window.addEventListener('pointermove',e=>{
  if(!press||trimming)return;const dx=e.clientX-press.x;
  if(!press.moved){if(Math.abs(dx)<6)return;press.moved=true;hideCut();press.el.classList.add('dragging','moving');document.body.classList.add('clip-moving');}
  press.el.style.transform=`translateX(${dx}px)`;clearDrop();const spot=dropSpot(e.clientX,press.el);if(spot)spot.el.classList.add(spot.after?'drop-after':'drop-before');
});
window.addEventListener('pointerup',e=>{
  if(!press)return;const p=press;press=null;if(!p.moved)return;
  justDragged=true;setTimeout(()=>{justDragged=false;},0);
  const spot=dropSpot(e.clientX,p.el);p.el.style.transform='';p.el.classList.remove('dragging','moving');document.body.classList.remove('clip-moving');clearDrop();
  if(!spot)return;let to=+spot.el.dataset.clip+(spot.after?1:0);const from=p.i;if(from<to)to-=1;if(from===to)return;
  selected=to;mutate(s=>{const [m]=s.clips.splice(from,1);s.clips.splice(to,0,m);}).then(()=>selectClip(to,false)).catch(error=>toast(error.message));
});
window.addEventListener('pointercancel',()=>{if(!press)return;press.el.style.transform='';press.el.classList.remove('dragging','moving');document.body.classList.remove('clip-moving');clearDrop();press=null;});

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

// 도구: 자르기(B, 마우스를 올리면 자를 위치 선이 보이고 클릭하면 그 자리에서 잘림) / 선택(A, 클릭하면 선택·이동)
let tool='blade';try{if(localStorage.getItem('studio-tool')==='select')tool='select';}catch{}
const toolBox=document.createElement('span');toolBox.className='tool-toggle';
toolBox.innerHTML='<button type="button" data-tool="select" title="선택 도구 (A)">↖ 선택 <kbd>A</kbd></button><button type="button" data-tool="blade" title="자르기 도구 (B): 클릭한 자리에서 잘라요">✂ 자르기 <kbd>B</kbd></button>';
$('ed-split')?.parentElement?.prepend(toolBox);
function setTool(t){tool=t;toolBox.querySelectorAll('[data-tool]').forEach(b=>b.classList.toggle('active',b.dataset.tool===t));track().classList.toggle('blade',t==='blade');if(t!=='blade')hideCut();try{localStorage.setItem('studio-tool',t);}catch{}}
toolBox.addEventListener('click',e=>{const b=e.target.closest('[data-tool]');if(b)setTool(b.dataset.tool);});
setTool(tool);
const cut=document.createElement('div');cut.className='cutline hidden';cut.innerHTML='<span></span>';track().parentElement.appendChild(cut);
function hideCut(){cut.classList.add('hidden');}
track().addEventListener('mousemove',e=>{
  if(tool!=='blade'||trimming||dragFrom!==null||press?.moved||e.target.closest('.trim')){hideCut();return;}
  const b=e.target.closest('[data-clip]');if(!b){hideCut();return;}
  const c=project?.state.clips[+b.dataset.clip];if(!c){hideCut();return;}
  const r=b.getBoundingClientRect(),tr=track().getBoundingClientRect(),f=Math.min(1,Math.max(0,(e.clientX-r.left)/r.width));
  const t=snap(c.start+(c.end-c.start)*f);let off=0;for(let k=0;k<+b.dataset.clip;k++)off+=project.state.clips[k].end-project.state.clips[k].start;
  cut.style.left=(e.clientX-tr.left+track().scrollLeft)+'px';cut.firstChild.textContent=clock(off+t-c.start,true);cut.classList.remove('hidden');
});
track().addEventListener('mouseleave',hideCut);
track().addEventListener('dragstart',hideCut);

// 캡컷처럼 구간마다 영상(썸네일 띠)·오디오(파형) 트랙을 위아래로 그린다
const strips={},peaks={};
function strip(id){const a=project?.assets.find(x=>x.id===id);if(!a||a.status!=='ready'||a.metadata?.has_video===false)return null;
  if(!strips[id]){const img=new Image();img.onload=()=>{img.ready=true;paint();};img.onerror=()=>{img.failed=true;};img.src='/api/assets/'+id+'/filmstrip.jpg';strips[id]=img;}return strips[id];}
function wave(id){const a=project?.assets.find(x=>x.id===id);if(!a||a.status!=='ready')return null;
  if(!peaks[id]){peaks[id]={loading:true};fetch('/api/assets/'+id+'/peaks',{credentials:'same-origin'}).then(r=>r.ok?r.json():null).then(d=>{peaks[id]=d&&d.peaks?d:{peaks:[],rate:10};paint();}).catch(()=>{peaks[id]={peaks:[],rate:10};});}
  return peaks[id].peaks?peaks[id]:null;}
function sized(cv){const d=devicePixelRatio||1,w=Math.max(1,Math.round(cv.clientWidth*d)),h=Math.max(1,Math.round(cv.clientHeight*d));if(cv.width!==w||cv.height!==h){cv.width=w;cv.height=h;}const ctx=cv.getContext('2d');ctx.clearRect(0,0,w,h);return [ctx,w,h];}
function paint(){
  if(!project)return;
  track().querySelectorAll('[data-clip]').forEach(b=>{
    const c=project.state.clips[+b.dataset.clip];if(!c)return;const len=Math.max(.001,c.end-c.start);
    const a=project.assets.find(x=>x.id===c.asset_id),dur=a?.metadata?.duration||c.end;
    const film=b.querySelector('.clip-film'),au=b.querySelector('.clip-wave');
    if(film){const [ctx,w,h]=sized(film),img=strip(c.asset_id);
      if(img?.ready){const n=Math.max(1,Math.round(img.naturalWidth/54)),tw=Math.max(8,h*54/96),tiles=Math.ceil(w/tw);
        for(let j=0;j<tiles;j++){const t=c.start+(j+.5)*tw/w*len,k=Math.min(n-1,Math.max(0,Math.floor(t/dur*n)));ctx.drawImage(img,k*54,0,54,96,j*tw,0,tw,h);}}
      else if(a?.metadata?.has_video===false){ctx.fillStyle='#ffffff80';ctx.font=`${Math.round(h*.4)}px sans-serif`;ctx.fillText('♫',8,h*.65);}}
    if(au){const [ctx,w,h]=sized(au),p=wave(c.asset_id);
      if(p&&p.peaks.length){const rate=p.rate||10,step=Math.max(2,Math.round(3*(devicePixelRatio||1))),bar=Math.max(1,step-1);ctx.fillStyle='#4fd8de';
        for(let x=0;x<w;x+=step){const t0=c.start+x/w*len,t1=c.start+(x+step)/w*len;let m=0;for(let q=Math.floor(t0*rate);q<=Math.min(p.peaks.length-1,Math.floor(t1*rate));q++)m=Math.max(m,p.peaks[q]||0);
          const bh=Math.max(1,Math.min(1,Math.sqrt(m))*(h-4));ctx.fillRect(x,h-bh-1,bar,bh);}}
      else{ctx.fillStyle='#4fd8de55';ctx.fillRect(0,h-2,w,1);}}
  });
}
window.paintTracks=paint;
new MutationObserver(()=>requestAnimationFrame(paint)).observe(track(),{childList:true});
if(window.ResizeObserver)new ResizeObserver(()=>requestAnimationFrame(paint)).observe(track());

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
  if(key==='b'||key==='B')return run(()=>setTool('blade'));
  if(key==='a'||key==='A')return run(()=>setTool('select'));
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
