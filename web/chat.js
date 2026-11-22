/* 편집 채팅(무료): chat-commands.js가 해석한 명령을 타임라인 편집으로 실행한다.
   app.js·editor.js의 전역(project, mutate, selected, selectClip, setSource, toast, editMulti, editorOps…)을 사용한다.
   한 번의 지시 = 한 번의 저장 = '되돌려' 한 번으로 취소. 대화 기록은 이 PC 브라우저에만 남는다. */
(function(){
const box=()=>$('chat-log');
const FPS=()=>project?.state.fps||30,snap=t=>Math.round(t*FPS())/FPS();
const len=c=>c.end-c.start;
const fmt=s=>s>=60?`${Math.floor(s/60)}분 ${(s%60).toFixed(1)}초`:`${(+s).toFixed(s<10?2:1).replace(/\.?0+$/,'')}초`;
const STYLE_MAP={해석:'commentary',영화:'commentary',드라마:'commentary',애니:'commentary',먹방:'cook_mukbang',원테이크:'oneshot',레시피:'recipe',요리:'recipe',맛집:'restaurant',식당:'restaurant',브이로그:'vlog',현장:'vlog',체험:'vlog',일상:'vlog'};
let thread=[];
const storeKey=()=>`studio-chat:${project?.id||'none'}`;
function load(){try{thread=JSON.parse(localStorage.getItem(storeKey())||'[]');}catch{thread=[];}render();}
function save(){try{localStorage.setItem(storeKey(),JSON.stringify(thread.slice(-80)));}catch{}}
function render(){
  const el=box();if(!el)return;
  if(!thread.length){el.innerHTML='';return;}
  el.innerHTML=thread.map(m=>`<div class="chat-msg ${m.who}${m.error?' error':''}">${m.html||`<p>${esc(m.text)}</p>`}</div>`).join('');
  el.scrollTop=el.scrollHeight;
}
function say(who,text,extra={}){thread.push({who,text,...extra});save();render();}

function clips(){if(!project)throw Error('먼저 프로젝트를 열거나 영상을 연결해 주세요.');return project.state.clips;}
function indexOf(ref,n){
  if(ref==='L')return n-1;
  if(ref==='S')return selected;
  const i=parseInt(ref,10)-1;return i;
}
function resolve(refs,{allowMany=true}={}){
  const n=clips().length;if(!n)throw Error('타임라인에 구간이 없어요. 먼저 자동 편집을 하거나 구간을 추가해 주세요.');
  let out=[];
  for(const r of refs){
    if(r==='ALL'){out=[...Array(n).keys()];continue;}
    if(r==='S'&&editMulti.size){out.push(...editMulti);continue;}
    if(typeof r==='object'){const a=indexOf(r.from,n),b=indexOf(r.to,n);for(let i=Math.min(a,b);i<=Math.max(a,b);i++)out.push(i);continue;}
    out.push(indexOf(r,n));
  }
  out=[...new Set(out)].sort((a,b)=>a-b);
  const bad=out.find(i=>!(i>=0&&i<n));
  if(bad!==undefined)throw Error(`${bad+1}번 구간은 없어요. 지금 구간은 1~${n}번이에요.`);
  if(!allowMany&&out.length!==1)throw Error('구간 하나만 지정해 주세요.');
  return out;
}
const label=ix=>ix.length===clips().length&&ix.length>1?'모든 구간':ix.length>3?`${ix.length}개 구간`:ix.map(i=>`${i+1}번`).join(', ');
function assetLength(id){const a=project.assets.find(a=>a.id===id);return a?.metadata?.duration??Infinity;}
function secondsOf(sec){return sec.frames!=null?sec.frames/FPS():sec.value;}
function seekEdited(t){
  const cs=clips();let off=0;
  for(let i=0;i<cs.length;i++){const l=len(cs[i]);if(t<off+l||i===cs.length-1){selectClip(i,false);setSource('/api/assets/'+cs[i].asset_id+'/video',snap(cs[i].start+Math.min(l,Math.max(0,t-off))),false);return i;}off+=l;}
}
function total(){return clips().reduce((s,c)=>s+len(c),0);}

async function run(cmd){
  switch(cmd.kind){
  case 'empty':return null;
  case 'help':return {html:'<p>이런 식으로 말하면 돼요(번호는 타임라인 구간 번호).</p><ul>'+CHAT_HELP.map(h=>`<li>${esc(h)}</li>`).join('')+'</ul><p class="muted">‘이 컷’·‘지금 컷’은 선택한 구간, ‘마지막 컷’은 맨 끝 구간이에요. 프레임 단위도 돼요(예: 3번 끝 5프레임 늘려).</p>'};
  case 'undo':if($('undo').disabled)throw Error('되돌릴 편집이 없어요.');$('undo').click();return '방금 편집을 되돌렸어요.';
  case 'redo':if($('redo').disabled)throw Error('다시 실행할 편집이 없어요.');$('redo').click();return '되돌린 편집을 다시 적용했어요.';
  case 'info':{const cs=clips();return `지금 구간 ${cs.length}개, 총 ${fmt(total())}예요.`+(cs.length?` 선택한 구간은 ${selected+1}번(${fmt(len(cs[selected]))})이에요.`:'');}
  case 'select':{const [i]=resolve([cmd.ref],{allowMany:false});editMulti.clear();selectClip(i,false);return `${i+1}번 구간(${fmt(len(clips()[i]))})을 선택했어요.`;}
  case 'play':{if(cmd.ref){const [i]=resolve([cmd.ref],{allowMany:false});selectClip(i,true);return `${i+1}번 구간부터 재생해요.`;}$('player').play();return '재생해요.';}
  case 'pause':$('player').pause();return '멈췄어요.';
  case 'seek':{const t=secondsOf(cmd.seconds);if(t>total())throw Error(`편집본은 ${fmt(total())}까지예요.`);const i=seekEdited(t);return `편집본 ${fmt(t)} 위치(${i+1}번 구간)로 이동했어요.`;}
  case 'silence':{const b=$('auto-cut');if(b.disabled)throw Error('지금은 무음 자동 편집을 시작할 수 없어요. 영상 준비가 끝났는지 확인해 주세요.');b.click();return '무음 자동 편집을 시작했어요. 진행 상황은 오른쪽에서 볼 수 있어요.';}
  case 'style':case 'guided':{
    if(cmd.style){const sel=$('guided-style'),want=STYLE_MAP[cmd.style];const opt=[...sel.options].find(o=>o.value===want)||[...sel.options].find(o=>o.textContent.includes(cmd.style));
      if(!opt)throw Error(`'${cmd.style}' 스타일을 찾지 못했어요.`);sel.value=opt.value;sel.dispatchEvent(new Event('change',{bubbles:true}));
      if(cmd.kind==='style'&&!cmd.start)return `편집 스타일을 '${opt.textContent.trim()}'(으)로 바꿨어요. 오른쪽 지침도 그 스타일 기본값으로 바뀌었어요.`;}
    const b=$('guided-start');if(b.disabled)throw Error('지금은 자동 편집을 시작할 수 없어요. 영상과 지침이 준비됐는지 오른쪽에서 확인해 주세요.');b.click();return '오른쪽 지침대로 자동 편집을 시작했어요. 끝나면 타임라인이 바뀌어요.';}
  case 'export':{
    if(cmd.what==='srt'){location.href=`/api/projects/${project.id}/captions.srt`;return 'SRT 자막 파일을 내려받아요.';}
    const g=$('guided-download'),q=$('quick-export');
    if(g&&!g.disabled){g.click();return '최종 MP4를 만들고 있어요. 다 되면 오른쪽에 다운로드 버튼이 생겨요.';}
    if(q&&!q.classList.contains('hidden')){q.click();return '고화질 MP4를 만들고 있어요.';}
    throw Error('아직 내보낼 편집본이 없어요.');}
  case 'delete':{
    const ix=resolve(cmd.refs);if(ix.length===clips().length)throw Error('모든 구간을 지우면 편집본이 비어요. 지울 구간 번호를 알려주세요.');
    const removed=ix.reduce((s,i)=>s+len(clips()[i]),0);editMulti.clear();
    await mutate(s=>{s.clips=s.clips.filter((_,i)=>!ix.includes(i));});
    if(clips().length)selectClip(Math.min(ix[0],clips().length-1),false);
    return `${label(ix)} 구간을 지웠어요(${fmt(removed)} 줄어 총 ${fmt(total())}).`;}
  case 'deleteShort':{
    const ix=clips().map((c,i)=>len(c)<cmd.under?i:-1).filter(i=>i>=0);
    if(!ix.length)return `${fmt(cmd.under)}보다 짧은 구간이 없어요.`;
    if(ix.length===clips().length)throw Error('모든 구간이 그보다 짧아서 지우지 않았어요.');
    await mutate(s=>{s.clips=s.clips.filter((_,i)=>!ix.includes(i));});
    return `${fmt(cmd.under)}보다 짧은 구간 ${ix.length}개(${ix.map(i=>i+1).join(', ')}번)를 지웠어요.`;}
  case 'resize':{
    const ix=resolve(cmd.refs),d=secondsOf(cmd.seconds);if(!(d>0))throw Error('몇 초를 바꿀지 알려주세요.');
    const sign=cmd.grow?1:-1,minLen=1/FPS();let clipped=0;
    await mutate(s=>{for(const i of ix){const c=s.clips[i],max=assetLength(c.asset_id);
      const before={start:c.start,end:c.end};
      if(cmd.side==='head'||cmd.side==='both')c.start=snap(Math.max(0,Math.min(c.end-minLen,c.start-sign*d)));
      if(cmd.side==='tail'||cmd.side==='both')c.end=snap(Math.min(max,Math.max(c.start+minLen,c.end+sign*d)));
      const dh=before.start-c.start,dt=c.end-before.end;
      if(c.visual_asset_id){c.visual_start=Math.max(0,(c.visual_start??c.start)-dh);c.visual_end=(c.visual_end??c.end)+dt;}
      if(Math.abs(Math.abs(dh)+Math.abs(dt)-d*(cmd.side==='both'?2:1))>1e-3)clipped++;}});
    const side={head:'앞',tail:'끝',both:'양쪽'}[cmd.side];
    return `${label(ix)} 구간 ${side}을 ${fmt(d)} ${cmd.grow?'늘렸어요':'줄였어요'}. 총 ${fmt(total())}.`+(clipped?` (${clipped}개 구간은 원본 처음·끝이나 최소 길이에 닿아 덜 바뀌었어요.)`:'');}
  case 'swap':{
    const a=resolve([cmd.refs[0]],{allowMany:false})[0],b=resolve([cmd.refs[1]],{allowMany:false})[0];if(a===b)throw Error('서로 다른 구간 두 개를 알려주세요.');
    await mutate(s=>{[s.clips[a],s.clips[b]]=[s.clips[b],s.clips[a]];});selectClip(b,false);return `${a+1}번과 ${b+1}번 구간 자리를 바꿨어요.`;}
  case 'move':{
    const [i]=resolve(cmd.refs,{allowMany:false});const n=clips().length;let to;
    if(cmd.to==='start')to=0;else if(cmd.to==='end')to=n-1;
    else{const t=resolve([cmd.target],{allowMany:false})[0];if(t===i)throw Error('같은 구간이에요.');to=cmd.to==='before'?(t>i?t-1:t):(t>i?t:t+1);}
    if(to===i)return `${i+1}번 구간은 이미 그 자리에 있어요.`;
    await mutate(s=>{const [c]=s.clips.splice(i,1);s.clips.splice(to,0,c);});selectClip(to,false);
    return `${i+1}번 구간을 ${to+1}번 자리로 옮겼어요.`;}
  case 'duplicate':{
    const ix=resolve(cmd.refs);await mutate(s=>{for(const i of [...ix].reverse())s.clips.splice(i+1,0,{...clone(s.clips[i]),id:uuid()});});
    return `${label(ix)} 구간을 복제해서 바로 뒤에 넣었어요.`;}
  case 'merge':{
    let ix=resolve(cmd.refs.length?cmd.refs:['S']);if(ix.length===1)ix=[ix[0],ix[0]+1];
    if(ix.some((v,k)=>k&&v!==ix[k-1]+1))throw Error('붙어 있는 구간끼리만 합칠 수 있어요(예: 3번이랑 4번).');
    const cs=ix.map(i=>clips()[i]);if(!cs[cs.length-1])throw Error('합칠 다음 구간이 없어요.');
    if(cs.some(c=>c.asset_id!==cs[0].asset_id||c.visual_asset_id))throw Error('같은 원본에서 나온 구간끼리만 합칠 수 있어요.');
    const start=cs[0].start,end=cs[cs.length-1].end;if(end<=start)throw Error('뒤 구간이 원본에서 더 앞에 있어서 합칠 수 없어요.');
    const gap=(end-start)-cs.reduce((s,c)=>s+len(c),0);
    await mutate(s=>{s.clips.splice(ix[0],ix.length,{...clone(cs[0]),end});});selectClip(ix[0],false);
    return `${ix.map(i=>i+1).join('·')}번 구간을 하나로 합쳤어요.`+(gap>0.04?` 사이에서 지웠던 원본 ${fmt(gap)}도 다시 들어갔어요.`:'');}
  case 'split':{
    if(cmd.here){await editorOps.splitHere();return '재생 위치에서 잘랐어요.';}
    const [i]=resolve([cmd.ref],{allowMany:false}),c=clips()[i];
    const at=cmd.at==='middle'?snap((c.start+c.end)/2):snap(c.start+secondsOf(cmd.at));
    if(!(at>c.start&&at<c.end))throw Error(`${i+1}번 구간은 ${fmt(len(c))} 길이라 그 위치에서 자를 수 없어요.`);
    if(c.visual_asset_id)throw Error('화면을 바꿔 얹은 구간은 채팅으로 자를 수 없어요. 타임라인에서 직접 잘라 주세요.');
    await mutate(s=>{const old=s.clips[i];s.clips.splice(i,1,{...old,end:at},{...clone(old),id:uuid(),start:at});});selectClip(i,false);
    return `${i+1}번 구간을 ${fmt(at-c.start)} 지점에서 둘로 나눴어요(${i+1}번·${i+2}번).`;}
  case 'trimHere':{await (cmd.side==='head'?editorOps.trimHead():editorOps.trimTail());return cmd.side==='head'?'재생 위치 앞부분을 지웠어요.':'재생 위치 뒷부분을 지웠어요.';}
  default:return {html:'<p>무슨 뜻인지 잘 모르겠어요. 이렇게 말해 보세요.</p><ul>'+CHAT_HELP.slice(0,4).map(h=>`<li>${esc(h)}</li>`).join('')+'</ul><p class="muted">‘도움말’로 전체 표현을 볼 수 있어요.</p>',miss:true};
  }
}

async function send(){
  const input=$('chat-input');const text=input.value.trim();if(!text)return;input.value='';
  say('me',text);
  try{
    const out=await run(parseCommand(text));if(out==null)return;
    if(typeof out==='string')say('bot',out);else say('bot','',{html:out.html,error:out.miss});
  }catch(e){say('bot',e.message,{error:true});}
}
bind('chat-send','click',send);
$('chat-input').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();send();}});
$('chat-chips').addEventListener('click',e=>{const b=e.target.closest('[data-say]');if(!b)return;$('chat-input').value=b.dataset.say;$('chat-input').focus();});
bind('chat-clear','click',()=>{thread=[];save();render();});
// 프로젝트를 바꾸면 그 프로젝트의 대화로 바꾼다
let shown=null;setInterval(()=>{const id=project?.id||'none';if(id!==shown){shown=id;load();}},500);
window.chatRun=t=>run(parseCommand(t));
})();
