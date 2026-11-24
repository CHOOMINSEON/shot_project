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
  editMulti.clear();layerSel.clear();focusLayer=false;selectedLayer=null;
  const c=project.state.clips[i],r=b.getBoundingClientRect(),f=Math.min(1,Math.max(0,(e.clientX-r.left)/r.width)),at=snap(c.start+(c.end-c.start)*f);
  if(tool==='blade'&&at>c.start+frame()/2&&at<c.end-frame()/2){hideCut();
    mutate(s=>{const old=s.clips[i];s.clips.splice(i,1,{...old,end:at},{...clone(old),id:uuid(),start:at});})
      .then(()=>{selectClip(i+1,false);}).catch(error=>toast(error.message));return;}
  $('player').pause();selectClip(i,false);setSource('/api/assets/'+c.asset_id+'/video',at,false);
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
  press={i:+b.dataset.clip,x:e.clientX,el:b,moved:false,y0:e.clientY,grab:(e.clientX-b.getBoundingClientRect().left)/Math.max(1e-6,b.getBoundingClientRect().width)*(project.state.clips[+b.dataset.clip].end-project.state.clips[+b.dataset.clip].start)};
});
window.addEventListener('pointermove',e=>{
  if(!press||trimming)return;const dx=e.clientX-press.x;
  if(!press.moved){if(Math.abs(dx)<6)return;press.moved=true;hideCut();press.el.classList.add('dragging','moving');document.body.classList.add('clip-moving');}
  press.el.style.transform=`translateX(${dx}px)`;press.el.dataset.dx=dx;clearDrop();document.querySelectorAll('.drop-row').forEach(r=>r.classList.remove('drop-row'));
  const row=window.timelineHooks?.rowAt(e.clientY);if(row&&row!==window.timelineHooks.mainRow){if(row!=='below')row.classList.add('drop-row');press.el.style.transform=`translate(${dx}px,${e.clientY-press.y0}px)`;}
  else{const spot=dropSpot(e.clientX,press.el);if(spot)spot.el.classList.add(spot.after?'drop-after':'drop-before');}requestAnimationFrame(()=>window.paintTracks?.());
});
window.addEventListener('pointerup',e=>{
  if(!press)return;const p=press;press=null;if(!p.moved)return;
  justDragged=true;setTimeout(()=>{justDragged=false;},0);
  const spot=dropSpot(e.clientX,p.el);p.el.style.transform='';delete p.el.dataset.dx;p.el.classList.remove('dragging','moving');document.body.classList.remove('clip-moving');clearDrop();document.querySelectorAll('.drop-row').forEach(r=>r.classList.remove('drop-row'));
  if(window.timelineHooks?.mainDropToLayer(p,e))return;
  if(!spot)return;let to=+spot.el.dataset.clip+(spot.after?1:0);const from=p.i;if(from<to)to-=1;if(from===to)return;
  selected=to;mutate(s=>{const [m]=s.clips.splice(from,1);s.clips.splice(to,0,m);}).then(()=>selectClip(to,false)).catch(error=>toast(error.message));
});
window.addEventListener('pointercancel',()=>{if(!press)return;press.el.style.transform='';press.el.classList.remove('dragging','moving');document.body.classList.remove('clip-moving');clearDrop();press=null;});

// 양끝 끌어서 길이 조절(원본 시간 기준, 프레임 단위로 맞춤)
track().addEventListener('pointerdown',e=>{
  const h=e.target.closest('.trim');if(!h)return;const b=h.closest('[data-clip]'),i=+b.dataset.clip,c=project.state.clips[i];
  e.preventDefault();e.stopPropagation();b.draggable=false;h.setPointerCapture?.(e.pointerId);
  trimming={i,side:h.dataset.trim,x:e.clientX,width:b.getBoundingClientRect().width,left:b.offsetLeft,len:c.end-c.start,start:c.start,end:c.end,el:b,dt:0};b.classList.add('trimming');h.classList.add('on');hideCut();
});
window.addEventListener('pointermove',e=>{
  if(!trimming)return;const t=trimming,dt=(e.clientX-t.x)/Math.max(20,t.width)*t.len;t.dt=dt;
  const a=project.assets.find(x=>x.id===project.state.clips[t.i].asset_id),max=a?.metadata.duration??Infinity;
  const v=t.side==='l'?Math.min(Math.max(0,t.start+dt),t.end-frame()):Math.max(Math.min(max,t.end+dt),t.start+frame());
  t.value=snap(v);const k=t.width/Math.max(1e-6,t.len),ns=t.side==='l'?t.value:t.start,ne=t.side==='l'?t.end:t.value;
  // 끄는 동안 클립 모양·썸네일·시간 말풍선을 바로 바꿔 보여준다
  t.el.style.left=(t.left+(ns-t.start)*k)+'px';t.el.style.width=Math.max(3,(ne-ns)*k-2)+'px';t.el.dataset.ts=ns;t.el.dataset.te=ne;
  window.trimTip?.(t.el.offsetLeft+(t.side==='l'?0:t.el.offsetWidth),`${t.side==='l'?'시작':'끝'} ${clock(t.value,true)} · 길이 ${(ne-ns).toFixed(2)}초`);
  requestAnimationFrame(()=>window.paintTracks?.());
});
window.addEventListener('pointerup',()=>{
  if(!trimming)return;const t=trimming;trimming=null;t.el.draggable=true;t.el.classList.remove('trimming');t.el.querySelectorAll('.trim.on').forEach(x=>x.classList.remove('on'));delete t.el.dataset.ts;delete t.el.dataset.te;window.trimTip?.(null);
  if(t.value===undefined||Math.abs(t.dt)<1e-6){window.layoutTimeline?.();return;}
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
function showCut(e){
  if(tool!=='blade'||trimming||ltrim||dragFrom!==null||press?.moved||lpress?.moved||e.target.closest('.trim')){hideCut();return;}
  if(!e.target.closest('[data-clip],[data-layer]')){hideCut();return;}
  const x=e.clientX-content.getBoundingClientRect().left;cut.style.left=x+'px';cut.firstChild.textContent=clock(x/pps(),true);cut.classList.remove('hidden');
}
track().addEventListener('mousemove',showCut);
track().addEventListener('mouseleave',hideCut);
track().addEventListener('dragstart',hideCut);

// ───── 캡컷식 다중 트랙 타임라인: 확대·축소, 가로·세로 스크롤, 레이어 5줄(기본 줄 포함 6줄) ─────
const MAX_LAYERS=5;
const wrap=track().parentElement;            // .track-wrap = 스크롤 영역
const content=document.createElement('div');content.className='tl-content';
const ruler=document.createElement('div');ruler.className='tl-ruler';
const mainRow=document.createElement('div');mainRow.className='tl-row main-row';mainRow.dataset.track='0';
const mainCanvas=document.createElement('canvas');mainCanvas.className='row-canvas';
const layerBox=document.createElement('div');layerBox.className='tl-layers';
wrap.prepend(content);mainRow.append(mainCanvas,track());content.append(ruler,mainRow,layerBox);
const lineHead=wrap.querySelector('.playhead');content.appendChild(lineHead);content.appendChild(cut);
const tip=document.createElement('div');tip.className='trim-tip hidden';content.appendChild(tip);
window.trimTip=(x,text)=>{if(x===null){tip.classList.add('hidden');return;}tip.style.left=x+'px';tip.style.top=(wrap.scrollTop+26)+'px';tip.textContent=text;tip.classList.remove('hidden');};
let zoom=1;try{zoom=Math.max(1,+localStorage.getItem('studio-zoom')||1);}catch{}
const layers=()=>project?.state.layers||[];
const layerLen=l=>l.end-l.start;
function total(){let t=editedLength();for(const l of layers())t=Math.max(t,l.at+layerLen(l));return Math.max(t,1);}
function pps(){return Math.max(.0001,(wrap.clientWidth-30)/total())*zoom;}
const timeAt=clientX=>Math.max(0,(clientX-content.getBoundingClientRect().left)/pps());
let selectedLayer=null,focusLayer=false;const layerSel=new Set();
// 확대·축소 막대(타임라인 제목 줄 오른쪽)
const zoomBox=document.createElement('span');zoomBox.className='zoom-box';
zoomBox.innerHTML='<button type="button" data-zoom="out" title="축소 (Ctrl+휠)">－</button><input type="range" id="tl-zoom" min="0" max="100" step="1" aria-label="타임라인 확대"><button type="button" data-zoom="in" title="확대 (Ctrl+휠)">＋</button><button type="button" data-zoom="fit" title="전체 보기">맞춤</button>';
document.querySelector('.timeline-heading')?.appendChild(zoomBox);
const zMax=400,toSlider=z=>Math.round(Math.log(z)/Math.log(zMax)*100),fromSlider=v=>Math.pow(zMax,v/100);
function setZoom(z,anchorClient){
  const old=pps(),r=wrap.getBoundingClientRect(),ax=anchorClient??(r.left+wrap.clientWidth/2),t=(ax-r.left+wrap.scrollLeft)/old;
  zoom=Math.min(zMax,Math.max(1,z));try{localStorage.setItem('studio-zoom',zoom);}catch{}
  layout();wrap.scrollLeft=Math.max(0,t*pps()-(ax-r.left));$('tl-zoom').value=toSlider(zoom);
}
zoomBox.addEventListener('click',e=>{const b=e.target.closest('[data-zoom]');if(!b)return;const k=b.dataset.zoom;
  setZoom(k==='fit'?1:zoom*(k==='in'?1.6:1/1.6),k==='fit'?undefined:(wrap.getBoundingClientRect().left+((playheadX()??wrap.scrollLeft+wrap.clientWidth/2)-wrap.scrollLeft)));});
$('tl-zoom').addEventListener('input',e=>setZoom(fromSlider(+e.target.value)));
// 휠: Ctrl=확대·축소, 그냥 굴리거나 Shift+휠은 가로로 이동(캡컷처럼), Alt+휠=위아래 줄 이동, 옆으로 기울이는 휠·터치패드 옆 밀기는 그대로 가로 이동
wrap.addEventListener('wheel',e=>{
  if(e.ctrlKey||e.metaKey){e.preventDefault();setZoom(zoom*Math.pow(1.0015,-e.deltaY),e.clientX);return;}
  const unit=e.deltaMode===1?32:e.deltaMode===2?wrap.clientWidth:1;
  if(e.altKey){e.preventDefault();wrap.scrollTop+=(e.deltaY||e.deltaX)*unit;return;}
  if(Math.abs(e.deltaX)>Math.abs(e.deltaY))return;
  e.preventDefault();wrap.scrollLeft+=e.deltaY*unit;},{passive:false});
window.timelineScroll=dir=>{wrap.scrollLeft+=dir*wrap.clientWidth*.12;};
// 재생헤드가 화면 밖이면 보이게 넘겨 준다
function keepVisible(){const x=playheadX();if(x===null)return;if(x<wrap.scrollLeft+20||x>wrap.scrollLeft+wrap.clientWidth-40)wrap.scrollLeft=Math.max(0,x-wrap.clientWidth/2);}
window.timelineKeepVisible=keepVisible;
window.timelineNudge=(dt)=>{const x=playheadX(),t=x===null?0:x/pps();seekTo(Math.max(0,t+dt));requestAnimationFrame(keepVisible);setTimeout(keepVisible,120);};
window.timelineJump=(dir)=>{const x=playheadX(),t=x===null?0:x/pps(),edges=[0];let off=0;for(const c of project.state.clips){off+=c.end-c.start;edges.push(off);}
  const e=dir<0?[...edges].reverse().find(v=>v<t-1e-3):edges.find(v=>v>t+1e-3);if(e===undefined)return;seekTo(Math.min(e,off-frame()/2));requestAnimationFrame(keepVisible);setTimeout(keepVisible,120);};
wrap.addEventListener('scroll',()=>requestAnimationFrame(()=>{drawRuler();paint();drawPlayhead();}));

// 레이어 줄 그리기
function renderLayers(){
  const used=layers().reduce((m,l)=>Math.max(m,l.track),0),rows=Math.min(MAX_LAYERS,used+1);
  let html='';
  for(let k=1;k<=rows;k++){
    html+=`<div class="tl-row layer-row" data-track="${k}"><canvas class="row-canvas"></canvas><span class="row-no">${k+1}</span>`;
    for(const l of layers().filter(x=>x.track===k)){
      const a=project.assets.find(x=>x.id===l.asset_id),audio=a?.metadata?.has_video===false;
      html+=`<div class="layer-clip ${audio?'audio':''} ${l.id===selectedLayer?'active':''} ${layerSel.has(l.id)?'multi':''}" data-layer="${l.id}" title="${esc(l.label||a?.name||'')}"><i class="trim trim-l" data-ltrim="l"></i><span class="clip-head">${audio?'♪ ':''}${esc(l.label||a?.name||'레이어')}</span><i class="trim trim-r" data-ltrim="r"></i></div>`;
    }
    html+='</div>';
  }
  layerBox.innerHTML=html;
}
function layout(){
  if(!project)return;const p=pps();content.style.width=Math.floor(total()*p+30)+'px';
  let off=0;track().querySelectorAll('[data-clip]').forEach(el=>{const c=project.state.clips[+el.dataset.clip];if(!c)return;const len=c.end-c.start;
    el.style.left=(off*p)+'px';el.style.width=Math.max(3,len*p-2)+'px';off+=len;});
  renderLayers();
  layerBox.querySelectorAll('[data-layer]').forEach(el=>{const l=layers().find(x=>x.id===el.dataset.layer);if(!l)return;
    el.style.left=(l.at*p)+'px';el.style.width=Math.max(3,layerLen(l)*p-2)+'px';});
  drawRuler();drawPlayhead();requestAnimationFrame(paint);
}
window.layoutTimeline=layout;
// 눈금자(보이는 범위만)
function drawRuler(){
  if(!project)return;const p=pps(),steps=[.1,.2,.5,1,2,5,10,15,30,60,120,300,600,1200];const step=steps.find(s=>s*p>=80)||1800;
  const sub=[10,5,2].find(n=>step*p/n>=7)||1,minor=step/sub;
  const a=Math.floor((wrap.scrollLeft/p)/step)*step,b=(wrap.scrollLeft+wrap.clientWidth)/p;let html='';
  for(let t=a;t<=b+step;t+=step){const x=t*p;html+=`<span class="mj" style="left:${x}px">${step<1?clock(t,true).slice(0,-2):clock(t)}</span>`;
    for(let k=1;k<sub;k++)html+=`<i class="${sub===10&&k===5?'md':''}" style="left:${x+k*minor*p}px"></i>`;}
  ruler.innerHTML=html;
}
// 재생헤드: 눈금자·빈 곳을 누르면 그 화면에서 멈추고, 누른 채 끌면 따라가며 보여준다(스페이스바로 재생).
function seekTo(t){
  const p=$('player');p.pause();
  if(rendered){p.currentTime=Math.min(t,(p.duration||t+1)-.01);drawPlayhead();return;}
  let off=0;const clips=project?.state.clips||[];
  for(let i=0;i<clips.length;i++){const c=clips[i],len=c.end-c.start;if(t<off+len||i===clips.length-1){
    const at=snap(c.start+Math.min(len-frame()/2,Math.max(0,t-off)));
    if(i!==selected||mode!=='edited')selectClip(i,false);
    setSource('/api/assets/'+c.asset_id+'/video',at,false);drawPlayhead();return;}off+=len;}
}
let scrub=null;
function startScrub(e){if(e.button!==0||!project?.state.clips.length)return;e.preventDefault();e.stopPropagation();hideCut();scrub=true;document.body.classList.add('scrubbing');seekTo(timeAt(e.clientX));}
const handle=document.createElement('b');handle.className='ph-handle';lineHead.appendChild(handle);
handle.addEventListener('pointerdown',startScrub);ruler.addEventListener('pointerdown',startScrub);
// 클립이 아닌 빈 곳(기본 줄·레이어 줄 바탕)
// 빈 곳: 그냥 클릭=그 위치로 이동·멈춤, 누른 채 끌기=사각형으로 여러 클립 선택(캡컷처럼)
const mbox=document.createElement('div');mbox.className='marquee hidden';content.appendChild(mbox);
let mq=null;
content.addEventListener('pointerdown',e=>{if(e.button!==0||scrub||e.target.closest('[data-clip],.layer-clip,.trim,.tl-ruler,.ph-handle'))return;
  if(!e.target.closest('.tl-row,.tl-layers,#timeline-track')&&e.target!==content)return;
  e.preventDefault();hideCut();const r=content.getBoundingClientRect();mq={x:e.clientX-r.left,y:e.clientY-r.top,cx:e.clientX,moved:false,add:e.shiftKey||e.ctrlKey||e.metaKey};});
function marqueeHits(){
  const b=mbox.getBoundingClientRect(),hit=el=>{const r=el.getBoundingClientRect();return r.right>b.left&&r.left<b.right&&r.bottom>b.top&&r.top<b.bottom;};
  const clips=new Set(),lays=new Set();
  track().querySelectorAll('[data-clip]').forEach(el=>{const on=hit(el);el.classList.toggle('multi',on);if(on)clips.add(+el.dataset.clip);});
  layerBox.querySelectorAll('[data-layer]').forEach(el=>{const on=hit(el);el.classList.toggle('multi',on);if(on)lays.add(el.dataset.layer);});
  return {clips,lays};
}
window.addEventListener('pointermove',e=>{if(!mq)return;const r=content.getBoundingClientRect(),x=e.clientX-r.left,y=e.clientY-r.top;
  if(!mq.moved){if(Math.abs(e.clientX-mq.cx)<6)if(Math.abs(y-mq.y)<6)return;mq.moved=true;document.body.classList.add('marqueeing');mbox.classList.remove('hidden');}
  const w=wrap.getBoundingClientRect();if(e.clientX>w.right-20)wrap.scrollLeft+=14;else if(e.clientX<w.left+20)wrap.scrollLeft-=14;
  mbox.style.left=Math.min(x,mq.x)+'px';mbox.style.top=Math.min(y,mq.y)+'px';mbox.style.width=Math.abs(x-mq.x)+'px';mbox.style.height=Math.abs(y-mq.y)+'px';marqueeHits();});
window.addEventListener('pointerup',e=>{if(!mq)return;const m=mq;mq=null;document.body.classList.remove('marqueeing');
  if(!m.moved){mbox.classList.add('hidden');if(project?.state.clips.length){editMulti.clear();layerSel.clear();seekTo(timeAt(e.clientX));draw();}return;}
  const {clips,lays}=marqueeHits();mbox.classList.add('hidden');
  if(!m.add){editMulti.clear();layerSel.clear();}clips.forEach(i=>editMulti.add(i));lays.forEach(id=>layerSel.add(id));
  selectedLayer=null;focusLayer=layerSel.size>0&&!editMulti.size;
  if(editMulti.size){const first=Math.min(...editMulti);if(first!==selected)selectClip(first,false);}
  draw();toast(`${editMulti.size+layerSel.size}개 선택했어요. Del로 삭제해요.`);});
function selectAll(){editMulti.clear();layerSel.clear();(project?.state.clips||[]).forEach((_,i)=>editMulti.add(i));layers().forEach(l=>layerSel.add(l.id));draw();toast(`전체 ${editMulti.size+layerSel.size}개 선택했어요.`);}
// 여러 개 삭제(기본 줄 클립 + 레이어 함께)
function removeMany(){
  const clips=[...editMulti],lays=[...layerSel];if(!clips.length&&!lays.length)return false;
  editMulti.clear();layerSel.clear();selectedLayer=null;focusLayer=false;const first=clips.length?Math.min(...clips):selected;
  return mutate(s=>{s.clips=s.clips.filter((_,i)=>!clips.includes(i));s.layers=(s.layers||[]).filter(l=>!lays.includes(l.id));selected=Math.max(0,Math.min(first,s.clips.length-1));})
    .then(()=>{if(project.state.clips.length)selectClip(Math.min(first,project.state.clips.length-1),false);toast(`${clips.length+lays.length}개를 삭제했어요.`);});
}
window.addEventListener('pointermove',e=>{if(!scrub)return;const r=wrap.getBoundingClientRect();
  if(e.clientX>r.right-20)wrap.scrollLeft+=12;else if(e.clientX<r.left+20)wrap.scrollLeft-=12;
  seekTo(timeAt(e.clientX));});
window.addEventListener('pointerup',()=>{if(!scrub)return;scrub=null;document.body.classList.remove('scrubbing');});

// 썸네일 띠·파형: 화면에 보이는 부분만 줄마다 캔버스 하나에 그린다(크게 확대해도 가볍게)
const strips={},peaks={};
function strip(id){const a=project?.assets.find(x=>x.id===id);if(!a||a.status!=='ready'||a.metadata?.has_video===false)return null;
  if(!strips[id]){const img=new Image();img.onload=()=>{img.ready=true;paint();};img.onerror=()=>{img.failed=true;};img.src='/api/assets/'+id+'/filmstrip.jpg';strips[id]=img;}return strips[id];}
function wave(id){const a=project?.assets.find(x=>x.id===id);if(!a||a.status!=='ready')return null;
  if(!peaks[id]){peaks[id]={loading:true};fetch('/api/assets/'+id+'/peaks',{credentials:'same-origin'}).then(r=>r.ok?r.json():null).then(d=>{peaks[id]=d&&d.peaks?d:{peaks:[],rate:10};paint();}).catch(()=>{peaks[id]={peaks:[],rate:10};});}
  return peaks[id].peaks?peaks[id]:null;}
function rowCanvas(cv,row){const d=devicePixelRatio||1,w=wrap.clientWidth,h=row.clientHeight;cv.style.left=wrap.scrollLeft+'px';cv.style.width=w+'px';cv.style.height=h+'px';
  const W=Math.max(1,Math.round(w*d)),H=Math.max(1,Math.round(h*d));if(cv.width!==W||cv.height!==H){cv.width=W;cv.height=H;}const ctx=cv.getContext('2d');ctx.setTransform(d,0,0,d,0,0);ctx.clearRect(0,0,w,h);return [ctx,w,h];}
function drawItem(ctx,vw,x0,w,y,h,assetId,start,len,filmFrac){
  if(x0>vw||x0+w<0)return;const a=project.assets.find(x=>x.id===assetId),dur=a?.metadata?.duration||start+len;
  const video=a?.metadata?.has_video!==false,fh=video?Math.round(h*filmFrac):0,wy=y+fh+(video?3:0),wh=h-fh-(video?3:0);
  ctx.save();ctx.beginPath();ctx.rect(Math.max(0,x0),y,Math.min(vw,x0+w)-Math.max(0,x0),h);ctx.clip();
  if(video){ctx.fillStyle='#0e5d63';ctx.fillRect(x0,y,w,fh);const img=strip(assetId);
    if(img?.ready){const n=Math.max(1,Math.round(img.naturalWidth/54)),tw=Math.max(8,fh*54/96);
      for(let j=Math.max(0,Math.floor(-x0/tw));j*tw<Math.min(w,vw-x0);j++){const t=start+(j+.5)*tw/w*len,k=Math.min(n-1,Math.max(0,Math.floor(t/dur*n)));ctx.drawImage(img,k*54,0,54,96,x0+j*tw,y,tw,fh);}}}
  ctx.fillStyle=video?'#0b4a4f':'#1f4d3a';ctx.fillRect(x0,wy,w,wh);const p=wave(assetId);
  if(p&&p.peaks.length){const rate=p.rate||10;ctx.fillStyle=video?'#4fd8de':'#7fe3a6';
    for(let x=Math.max(0,Math.floor(-x0));x<Math.min(w,vw-x0);x+=3){const t0=start+x/w*len,t1=start+(x+3)/w*len;let m=0;
      for(let q=Math.floor(t0*rate);q<=Math.min(p.peaks.length-1,Math.floor(t1*rate));q++)m=Math.max(m,p.peaks[q]||0);
      const bh=Math.max(1,Math.min(1,Math.sqrt(m))*(wh-3));ctx.fillRect(x0+x,wy+wh-bh-1,2,bh);}}
  ctx.restore();
}
function paint(){
  if(!project)return;const sx=wrap.scrollLeft;
  {const [ctx,vw,h]=rowCanvas(mainCanvas,mainRow);
    track().querySelectorAll('[data-clip]').forEach(el=>{const c=project.state.clips[+el.dataset.clip];if(!c)return;
      const cs=el.dataset.ts?+el.dataset.ts:c.start,ce=el.dataset.te?+el.dataset.te:c.end;drawItem(ctx,vw,el.offsetLeft+(+el.dataset.dx||0)-sx,el.offsetWidth,0,h,c.asset_id,cs,ce-cs,.64);});}
  layerBox.querySelectorAll('.layer-row').forEach(row=>{const [ctx,vw,h]=rowCanvas(row.querySelector('canvas'),row);
    row.querySelectorAll('[data-layer]').forEach(el=>{const l=layers().find(x=>x.id===el.dataset.layer);if(!l)return;
      drawItem(ctx,vw,el.offsetLeft-sx,el.offsetWidth,0,h,l.asset_id,l.start,layerLen(l),.6);});});
}
window.paintTracks=paint;
layerBox.addEventListener('mousemove',showCut);layerBox.addEventListener('mouseleave',hideCut);
new MutationObserver(()=>{layout();resolvePending();}).observe(track(),{childList:true});
if(window.ResizeObserver)new ResizeObserver(()=>requestAnimationFrame(layout)).observe(wrap);
$('tl-zoom').value=toSlider(zoom);

// 레이어 구간: 끌어서 옮기기(가로=시간, 세로=줄), 양끝 길이 조절, 클릭(자르기 도구=자르기, 선택 도구=선택), 기본 줄로 끌어 올리기
let lpress=null,ltrim=null;
function rowAt(y){for(const row of [mainRow,...layerBox.querySelectorAll('.layer-row')]){const r=row.getBoundingClientRect();if(y>=r.top&&y<r.bottom)return row;}
  const rows=layerBox.querySelectorAll('.layer-row'),last=rows[rows.length-1];return last&&y>=last.getBoundingClientRect().bottom?'below':null;}
layerBox.addEventListener('pointerdown',e=>{
  if(e.button!==0)return;const el=e.target.closest('[data-layer]');if(!el)return;const l=layers().find(x=>x.id===el.dataset.layer);if(!l)return;
  e.preventDefault();const h=e.target.closest('[data-ltrim]');
  if(h){h.classList.add('on');ltrim={id:l.id,side:h.dataset.ltrim,x:e.clientX,el,l:{...l}};return;}
  lpress={id:l.id,x:e.clientX,y:e.clientY,el,l:{...l},moved:false};
});
window.addEventListener('pointermove',e=>{
  if(ltrim){const t=ltrim,p=pps(),dt=(e.clientX-t.x)/p,a=project.assets.find(x=>x.id===t.l.asset_id),max=a?.metadata.duration??Infinity;
    if(t.side==='l'){const s=snap(Math.min(Math.max(0,t.l.start+dt,t.l.start-t.l.at),t.l.end-frame()));t.v={start:s,at:snap(t.l.at+s-t.l.start)};}
    else t.v={end:snap(Math.max(Math.min(max,t.l.end+dt),t.l.start+frame()))};
    const n={...t.l,...t.v};t.el.style.left=n.at*p+'px';t.el.style.width=Math.max(3,(n.end-n.start)*p-2)+'px';t.el.classList.add('trimming');
    window.trimTip((t.side==='l'?n.at:n.at+n.end-n.start)*p,`${t.side==='l'?'시작':'끝'} ${clock(t.side==='l'?n.start:n.end,true)} · 길이 ${(n.end-n.start).toFixed(2)}초`);requestAnimationFrame(paint);return;}
  if(!lpress)return;const dx=e.clientX-lpress.x,dy=e.clientY-lpress.y;
  if(!lpress.moved){if(Math.abs(dx)<6&&Math.abs(dy)<6)return;lpress.moved=true;hideCut();lpress.el.classList.add('moving');document.body.classList.add('clip-moving');}
  const at=snap(Math.max(0,lpress.l.at+dx/pps()));lpress.at=at;lpress.el.style.left=at*pps()+'px';
  const row=rowAt(e.clientY);content.querySelectorAll('.drop-row').forEach(r=>r.classList.remove('drop-row'));clearDrop();
  if(row===mainRow){lpress.target='main';mainRow.classList.add('drop-row');const spot=dropSpot(e.clientX,null);if(spot)spot.el.classList.add(spot.after?'drop-after':'drop-before');lpress.spot=spot;}
  else if(row==='below'){lpress.target=Math.min(MAX_LAYERS,layerBox.children.length+1);}
  else if(row){lpress.target=+row.dataset.track;row.classList.add('drop-row');if(row!==lpress.el.parentElement)row.appendChild(lpress.el);}
  requestAnimationFrame(paint);
});
window.addEventListener('pointerup',e=>{
  if(ltrim){const t=ltrim;ltrim=null;window.trimTip(null);t.el.classList.remove('trimming');t.el.querySelectorAll('.trim.on').forEach(x=>x.classList.remove('on'));if(!t.v)return;mutate(s=>{const l=s.layers.find(x=>x.id===t.id);if(l)Object.assign(l,t.v);}).catch(error=>toast(error.message));return;}
  if(!lpress)return;const p=lpress;lpress=null;document.body.classList.remove('clip-moving');content.querySelectorAll('.drop-row').forEach(r=>r.classList.remove('drop-row'));clearDrop();
  if(!p.moved){layerClick(p.l,e);return;}
  if(p.target==='main'){
    const a=project.assets.find(x=>x.id===p.l.asset_id);if(a?.metadata?.has_video===false){toast('소리만 있는 파일은 기본 줄에 놓을 수 없어요.');layout();return;}
    let to=p.spot?+p.spot.el.dataset.clip+(p.spot.after?1:0):project.state.clips.length;
    mutate(s=>{s.layers=s.layers.filter(x=>x.id!==p.id);s.clips.splice(to,0,{id:uuid(),asset_id:p.l.asset_id,start:p.l.start,end:p.l.end,label:p.l.label||'',frame:p.l.frame||{mode:'fit',x:.5,y:.5,zoom:1}});}).catch(error=>toast(error.message));return;}
  const track=typeof p.target==='number'?p.target:p.l.track;
  mutate(s=>{const l=s.layers.find(x=>x.id===p.id);if(l){l.at=p.at??l.at;l.track=track;}}).catch(error=>{toast(error.message);layout();});
});
function layerClick(l,e){
  const t=timeAt(e.clientX),src=snap(l.start+(t-l.at));
  if(tool==='blade'&&src>l.start+frame()/2&&src<l.end-frame()/2){hideCut();
    return mutate(s=>{const i=s.layers.findIndex(x=>x.id===l.id);if(i<0)return;const old=s.layers[i];const right={...clone(old),id:uuid(),start:src,at:snap(old.at+src-old.start)};old.end=src;s.layers.splice(i+1,0,right);selectedLayer=right.id;}).catch(error=>toast(error.message));}
  editMulti.clear();layerSel.clear();selectedLayer=l.id;focusLayer=true;layout();seekTo(t);draw();
}
function removeLayer(){if(!selectedLayer)throw Error('삭제할 레이어를 선택해 주세요.');const id=selectedLayer;selectedLayer=null;focusLayer=false;return mutate(s=>{s.layers=(s.layers||[]).filter(x=>x.id!==id);});}

// 기본 줄 구간을 아래 레이어 줄로 끌어내리기(편집 중 위치 그대로)
function mainDropToLayer(p,e){
  const row=rowAt(e.clientY);if(!row||row===mainRow)return false;
  const k=row==='below'?Math.min(MAX_LAYERS,layerBox.children.length+1):+row.dataset.track;const c=project.state.clips[p.i];if(!c)return false;
  const at=snap(Math.max(0,timeAt(e.clientX)-p.grab));
  mutate(s=>{s.clips.splice(p.i,1);s.layers=s.layers||[];s.layers.push({id:uuid(),track:k,asset_id:c.asset_id,start:c.start,end:c.end,at,label:c.label||'',frame:c.frame||{mode:'fit',x:.5,y:.5,zoom:1}});}).catch(error=>toast(error.message));
  return true;
}
window.timelineHooks={mainDropToLayer,rowAt:y=>rowAt(y),mainRow,timeAt};

// PC에서 영상·오디오를 레이어 줄(또는 그 아래 빈 곳)에 끌어다 놓으면 그 줄·그 시간에 깔린다
const pending=[];
layerBox.addEventListener('dragover',e=>{if(![...(e.dataTransfer?.types||[])].includes('Files'))return;e.preventDefault();e.stopPropagation();e.dataTransfer.dropEffect='copy';
  content.querySelectorAll('.drop-row').forEach(r=>r.classList.remove('drop-row'));e.target.closest('.layer-row')?.classList.add('drop-row');});
layerBox.addEventListener('dragleave',e=>{if(!layerBox.contains(e.relatedTarget))content.querySelectorAll('.drop-row').forEach(r=>r.classList.remove('drop-row'));});
layerBox.addEventListener('drop',async e=>{if(![...(e.dataTransfer?.types||[])].includes('Files'))return;e.preventDefault();e.stopPropagation();
  content.querySelectorAll('.drop-row').forEach(r=>r.classList.remove('drop-row'));
  const row=e.target.closest('.layer-row'),k=row?+row.dataset.track:Math.min(MAX_LAYERS,layerBox.children.length+1),at=snap(timeAt(e.clientX));
  try{const files=(await droppedFiles(e.dataTransfer)).filter(isMedia).sort(byName);if(!files.length)throw Error('영상·오디오 파일만 놓을 수 있어요.');
    const known=new Set((project?.assets||[]).map(a=>a.id));
    files.forEach(f=>pending.push({name:f.name,track:k,at,known}));await uploadMedia(files,false);}catch(error){toast(error.message);}
});
let resolving=false;
function resolvePending(){
  if(resolving||!pending.length||!project)return;
  const ready=pending.map(p=>({p,a:project.assets.find(a=>a.name===p.name&&a.status==='ready'&&!p.known.has(a.id)&&!layers().some(l=>l.asset_id===a.id))})).filter(x=>x.a);
  if(!ready.length)return;resolving=true;
  ready.forEach(x=>pending.splice(pending.indexOf(x.p),1));
  mutate(s=>{s.layers=s.layers||[];const cursor={};
    for(const {p,a} of ready){const dur=Math.floor(a.metadata.duration*(s.fps||30))/(s.fps||30);
      s.clips=s.clips.filter(c=>!(c.asset_id===a.id&&c.start===0));        // 올리면서 기본 줄 끝에 자동으로 붙은 것은 치운다
      const key=p.track+':'+p.at,at=cursor[key]??p.at;cursor[key]=at+dur;
      s.layers.push({id:uuid(),track:p.track,asset_id:a.id,start:0,end:dur,at,label:a.name.replace(/\.[^.]+$/,''),frame:{mode:'fit',x:.5,y:.5,zoom:1}});}
  }).catch(error=>toast(error.message)).finally(()=>{resolving=false;});
}

// 재생 위치 표시선(모든 줄을 가로지름)
function playheadX(){const h=playhead();if(!h)return null;let off=0;for(let i=0;i<h.index;i++){const c=project.state.clips[i];off+=c.end-c.start;}
  return (off+h.time-project.state.clips[h.index].start)*pps();}
function drawPlayhead(){const el=lineHead,x=playheadX();if(x===null){el.classList.add('hidden');return;}el.style.left=x+'px';el.style.top=wrap.scrollTop+'px';el.style.height=wrap.clientHeight+'px';el.classList.remove('hidden');}
$('player').addEventListener('timeupdate',drawPlayhead);$('player').addEventListener('seeked',drawPlayhead);
// 재생 중에는 매 프레임 선을 옮기고, 화면 밖으로 나가면 따라 스크롤한다.
let phLoop=0;function phTick(){const p=$('player');drawPlayhead();
  const x=playheadX();if(x!==null&&!scrub&&(x>wrap.scrollLeft+wrap.clientWidth-30||x<wrap.scrollLeft))wrap.scrollLeft=Math.max(0,x-40);
  phLoop=p.paused?0:requestAnimationFrame(phTick);}
$('player').addEventListener('play',()=>{if(!phLoop)phLoop=requestAnimationFrame(phTick);});

// 단축키(입력창에 글자를 쓰는 중에는 동작하지 않음)
document.addEventListener('keydown',e=>{
  const tag=(e.target.tagName||'').toLowerCase();if(['input','textarea','select'].includes(tag)||e.target.isContentEditable||!project)return;
  const key=e.key,ctrl=e.ctrlKey||e.metaKey,run=fn=>{e.preventDefault();try{Promise.resolve(fn()).catch(x=>toast(x.message));}catch(x){toast(x.message);}};
  const p=$('player');
  if(ctrl&&key.toLowerCase()==='z')return run(()=>$(e.shiftKey?'redo':'undo').click());
  if(ctrl&&key.toLowerCase()==='y')return run(()=>$('redo').click());
  if(ctrl&&key.toLowerCase()==='a')return run(selectAll);
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
  if(key==='Delete'||key==='Backspace')return run(()=>(editMulti.size>1||layerSel.size)?removeMany():focusLayer&&selectedLayer?removeLayer():removeSelected());
  if(key===' ')return run(()=>{if(!p.paused)return p.pause();if(!p.src&&project.state.clips.length)seekTo(0);return p.play();});
  if(key==='ArrowLeft'||key==='ArrowRight')return run(()=>window.timelineNudge((key==='ArrowLeft'?-1:1)*(e.shiftKey?1:frame())));
  if(key===','||key==='.'||key==='<'||key==='>')return run(()=>window.timelineNudge((key===','||key==='<'?-1:1)*(e.shiftKey?1:frame())));
  if(key==='ArrowUp'||key==='ArrowDown')return run(()=>window.timelineJump(key==='ArrowUp'?-1:1));
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
